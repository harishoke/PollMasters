// server.js
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, delay, jidNormalizedUser, getAggregateVotesInPollMessage, proto } = require('@whiskeysockets/baileys'); // Added getAggregateVotesInPollMessage and proto
const { Boom } = require('@hapi/boom');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const pino = require('pino');
const fs = require('fs').promises;
const path = require('path');
const crypto = require('crypto');

const POLL_STORAGE_FILE = path.join(__dirname, 'active_polls_storage.json');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: { origin: "*", methods: ["GET", "POST"] }
});
const PORT = 3000;
app.use(express.json());

let sock;
let clientReady = false;
let qrCodeData = null;

let activePolls = {}; // Store for polls sent in the current session

async function saveActivePolls() {
    try {
        await fs.writeFile(POLL_STORAGE_FILE, JSON.stringify(activePolls, null, 2));
        console.log('Active polls saved to storage.');
    } catch (error) {
        console.error('Error saving active polls:', error);
    }
}

async function loadActivePolls() {
    try {
        if (await fs.stat(POLL_STORAGE_FILE).then(() => true).catch(() => false)) {
            const data = await fs.readFile(POLL_STORAGE_FILE, 'utf-8');
            activePolls = JSON.parse(data);
            console.log('Active polls loaded from storage.');
        } else {
            console.log('No active polls storage file found. Starting fresh.');
            activePolls = {};
        }
    } catch (error) {
        console.error('Error loading active polls:', error);
        activePolls = {}; // Reset on error to prevent issues
    }
}

function generateOptionSha256(optionText) {
    return crypto.createHash('sha256').update(Buffer.from(optionText)).digest('hex');
}

async function connectToWhatsApp() {
    await loadActivePolls(); // Load polls before starting connection
    console.log('Initializing Baileys WhatsApp Client (Poll Focus)...');
    const { state, saveCreds } = await useMultiFileAuthState('baileys_auth_info');
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`using Baileys version ${version.join('.')}`);

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: true, // QR code එක terminal එකේ පෙන්වයි
        browser: ['WhatsApp Poll Enhanced', 'Chrome', '1.0'],
        logger: pino({ level: 'debug' }) // DEBUG level to see more logs
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (connection === 'open') {
            console.log('Baileys WhatsApp Client is ready! (Poll Focus)');
            clientReady = true;
            qrCodeData = null;
            io.emit('client_status', 'ready');
            io.emit('whatsapp_user', sock.user); // Send user info
        } else if (connection === 'close') {
            clientReady = false;
            qrCodeData = null; // Clear QR on close
            const shouldReconnect = (lastDisconnect?.error instanceof Boom)?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('Connection closed due to ', lastDisconnect?.error, ', reconnecting ', shouldReconnect);
            io.emit('client_status', 'disconnected');
            if (shouldReconnect) {
                connectToWhatsApp();
            } else {
                console.log('Logged out, not reconnecting. Please delete baileys_auth_info and restart.');
                // Optionally, inform GUI about permanent logout
                io.emit('client_status', 'logged_out');
            }
        }
        if (qr) {
            qrCodeData = qr;
            io.emit('qr_code', qr);
            io.emit('client_status', 'qr_pending');
            console.log('QR code generated. Scan it.');
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        const msg = messages[0];
        if (!msg.message) return; // Ignore if message content is empty

        // console.log('Received message:', JSON.stringify(msg, undefined, 2)); // Detailed log for incoming messages

        if (msg.message.pollUpdateMessage) {
            const pollUpdate = msg.message.pollUpdateMessage;
            const originalPollMsgKey = pollUpdate.pollCreationMessageKey;
            // voterJid can be from msg.key.participant (group) or msg.key.remoteJid (DM, if direct poll update)
            // However, poll updates in groups are usually from the group jid with a participant field inside msg.
            const voterJid = msg.key.participant || msg.participant || msg.key.remoteJid;


            if (!originalPollMsgKey || !originalPollMsgKey.id) {
                console.warn("Poll update received without original poll message key ID. Skipping. Details:", JSON.stringify(originalPollMsgKey));
                return;
            }
            const pollMsgId = originalPollMsgKey.id;

            console.log(`Poll Update for Poll ID: ${pollMsgId} from Voter: ${voterJid}`);
            // console.log('Poll Update Raw Details:', JSON.stringify(pollUpdate, undefined, 2));

            if (activePolls[pollMsgId]) {
                const poll = activePolls[pollMsgId];
                let selectedOptionHashes = [];

                // --- TypeError නිවැරදි කිරීම මෙතන ---
                if (pollUpdate.votes && Array.isArray(pollUpdate.votes)) {
                    selectedOptionHashes = pollUpdate.votes.map(voteBuffer => {
                        if (Buffer.isBuffer(voteBuffer)) {
                            return voteBuffer.toString('hex');
                        } else {
                            console.warn(`Item in pollUpdate.votes for poll ${pollMsgId} is not a Buffer. Item:`, voteBuffer);
                            return null;
                        }
                    }).filter(hash => hash !== null);
                } else {
                    console.log(`Poll update for ${pollMsgId} (voter: ${voterJid}) did not contain a valid 'votes' array or it's empty. Current votes data:`, pollUpdate.votes);
                }
                // --- නිවැරදි කිරීම අවසන් ---

                // Recalculate entire poll results based on all stored voter responses for this poll
                // This is more robust for handling vote changes and ensuring count accuracy.

                // 1. Update this voter's current selection
                if (selectedOptionHashes.length > 0) {
                    poll.voters[voterJid] = selectedOptionHashes; // Store/update this voter's current selection
                } else {
                    // If selectedOptionHashes is empty, it means the voter deselected all their options (if possible)
                    // or the update didn't contain votes. We might remove their entry or handle as no vote.
                    delete poll.voters[voterJid]; // Voter retracted their vote(s)
                    console.log(`Voter ${voterJid} retracted votes for poll ${pollMsgId}`);
                }

                // 2. Recalculate all results for the poll
                // Reset current results to 0
                for (const optionText in poll.results) {
                    poll.results[optionText] = 0;
                }

                // Iterate through all stored voters and their selections
                for (const singleVoterJid in poll.voters) {
                    const voterSelections = poll.voters[singleVoterJid]; // This is an array of hashes
                    if (Array.isArray(voterSelections)) {
                        voterSelections.forEach(hash => {
                            const optionText = poll.optionHashes[hash];
                            if (optionText && poll.results.hasOwnProperty(optionText)) {
                                poll.results[optionText]++;
                            }
                        });
                    }
                }
                // --- End of recalculation logic ---

                console.log(`Updated poll results for ${pollMsgId}:`, poll.results);
                console.log(`Voters for ${pollMsgId}:`, poll.voters)
                io.emit('poll_update_to_gui', {
                    pollMsgId: pollMsgId,
                    results: poll.results,
                    question: poll.question,
                    options: poll.options, // Pass original options array
                    voters: poll.voters, // Pass updated voters object
                    selectableCount: poll.selectableCount // Pass selectableCount for context
                });
                await saveActivePolls(); // Save polls after update
            } else {
                console.warn(`Received poll update for an unknown or inactive poll ID: ${pollMsgId}. Active polls:`, Object.keys(activePolls));
            }
        }
    });
}

connectToWhatsApp();

io.on('connection', (socket) => {
    console.log('GUI connected via Socket.IO:', socket.id);
    socket.emit('client_status', clientReady ? 'ready' : (qrCodeData ? 'qr_pending' : 'disconnected'));
    if (clientReady && sock.user) socket.emit('whatsapp_user', sock.user);
    if (qrCodeData) socket.emit('qr_code', qrCodeData);
    socket.emit('initial_poll_data', activePolls); // Send all current poll data
});

app.get('/status', (req, res) => res.json({ status: clientReady ? 'ready' : (qrCodeData ? 'qr_pending' : 'disconnected'), qrCode: qrCodeData, user: clientReady && sock ? sock.user : null }));

app.post('/send-poll', async (req, res) => {
    if (!clientReady || !sock) return res.status(400).json({ success: false, message: 'Baileys client not ready.' });

    const { chatId, question, options, allowMultipleAnswers } = req.body;

    if (!chatId || !question || !options || !Array.isArray(options) || options.length < 1) {
        return res.status(400).json({ success: false, message: 'chatId, question, and at least one option required.' });
    }
    if (options.length > 12) {
        return res.status(400).json({ success: false, message: 'Maximum of 12 poll options allowed.' });
    }

    try {
        // await delay(500 + Math.random() * 1000); // Optional delay

        const pollMessagePayload = {
            name: question,
            values: options,
            selectableCount: allowMultipleAnswers ? 0 : 1,
        };

        const sentMsg = await sock.sendMessage(chatId, { poll: pollMessagePayload });
        const pollMsgId = sentMsg.key.id;

        const optionHashes = {};
        const initialResults = {};
        options.forEach(opt => {
            const hash = generateOptionSha256(opt); // Use the same hash function
            optionHashes[hash] = opt;
            initialResults[opt] = 0;
        });

        activePolls[pollMsgId] = {
            question: question,
            options: options, // Store original option strings
            optionHashes: optionHashes, // Store mapping from hash to option string
            results: initialResults, // Store results by option string
            voters: {}, // Store votes by voter JID -> array of selected hashes
            chatId: chatId,
            timestamp: typeof sentMsg.messageTimestamp === 'number' ? sentMsg.messageTimestamp * 1000 : Date.now(), // Ensure JS timestamp
            selectableCount: pollMessagePayload.selectableCount,
            // messageDetails: sentMsg // Optional: store full sent message
        };

        console.log(`Poll sent successfully to ${chatId}, Msg ID: ${pollMsgId}`);
        console.log("Active Polls now:", activePolls);
        // Emit the newly created poll data for GUI to update its list
        io.emit('new_poll_sent', { pollMsgId: pollMsgId, pollData: activePolls[pollMsgId] });
        await saveActivePolls(); // Save polls after sending a new one
        res.json({ success: true, message: 'Poll sent successfully!', pollMsgId: pollMsgId });

    } catch (error) {
        console.error('Error sending poll:', error);
        res.status(500).json({ success: false, message: 'Failed to send poll.', error: error.message });
    }
});

app.get('/get-chats', async (req, res) => {
    if (!clientReady || !sock) {
        return res.status(400).json({ success: false, message: 'Baileys WhatsApp client is not ready.' });
    }
    try {
        const simplifiedChats = [];
        const groups = await sock.groupFetchAllParticipating();
        for (const [jid, group] of Object.entries(groups)) {
            if (group.subject) {
                simplifiedChats.push({ id: jid, name: group.subject, isGroup: true });
            }
        }
         // sock.contacts might not be populated immediately or in all Baileys versions by default
         // It's better to rely on specific functions if needed, or ensure it's populated
        // For now, this might return an empty list or be unreliable.
        // Consider using sock.getContacts() or similar if you need a full contact list.

        simplifiedChats.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
        res.json({ success: true, chats: simplifiedChats });
    } catch (error) {
        console.error('Error fetching chats:', error);
        res.status(500).json({ success: false, message: 'Failed to fetch chats.', error: error.message });
    }
});

app.post('/logout', async (req, res) => {
    console.log('Received logout request.');
    if (sock) {
        try {
            await sock.logout(); // This logs out from WhatsApp Web
            console.log('Baileys client logged out successfully from WhatsApp.');
        } catch (error) {
            console.error('Error during Baileys logout from WhatsApp:', error);
        } finally {
            // Clean up local session state
            if (sock && typeof sock.end === 'function') {
                sock.end(new Error('Logged out by user request')); // Properly close the socket connection
            }
            const sessionPath = path.join(__dirname, 'baileys_auth_info');
            try {
                await fs.rm(sessionPath, { recursive: true, force: true });
                console.log('Session folder "baileys_auth_info" deleted.');
            } catch (err) {
                console.error('Error deleting session folder:', err.code === 'ENOENT' ? 'Session folder not found.' : err);
            }
            clientReady = false;
            qrCodeData = null;
            activePolls = {}; // Clear active polls on logout
            await saveActivePolls(); // Save the cleared state
            sock = undefined; // Clear the sock variable

            io.emit('client_status', 'disconnected');
            io.emit('initial_poll_data', activePolls); // Send empty polls
            res.json({ success: true, message: 'Logged out and local session cleared. Please restart the server to connect a new account.' });
        }
    } else {
        // Also clear local session if sock is somehow undefined but user wants to "logout"
        const sessionPath = path.join(__dirname, 'baileys_auth_info');
            try {
                await fs.rm(sessionPath, { recursive: true, force: true });
                console.log('Session folder "baileys_auth_info" deleted (sock was undefined).');
            } catch (err) {
                console.error('Error deleting session folder (sock was undefined):', err.code === 'ENOENT' ? 'Session folder not found.' : err);
            }
        clientReady = false; qrCodeData = null; activePolls = {};
        await saveActivePolls(); // Save the cleared state even if sock was undefined
        io.emit('client_status', 'disconnected'); io.emit('initial_poll_data', activePolls);
        res.status(400).json({ success: false, message: 'Client was not active, but attempted to clear session.' });
    }
});

app.get('/get-all-poll-data', (req, res) => {
    res.json({ success: true, polls: activePolls });
});

server.listen(PORT, () => {
    console.log(`Node.js server (Poll Focus) listening on port ${PORT}`);
});
