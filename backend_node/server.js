// server.js (முக்கிய වෙනස්කම්)
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, delay, jidNormalizedUser } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const pino = require('pino');
const fs = require('fs').promises;
const path = require('path');
const crypto = require('crypto'); // To generate SHA256 hashes for poll options

const app =express();
const server = http.createServer(app);
const io = new Server(server, {
    cors: { origin: "*", methods: ["GET", "POST"] }
});
const PORT = 3000;
app.use(express.json());

let sock;
let clientReady = false;
let qrCodeData = null;

// In-memory store for active polls and their results
// Structure:
// {
//   "pollMsgId_1": {
//     question: "Poll Question 1",
//     options: ["Option A", "Option B"], // Original options text
//     optionHashes: { "hashOfA": "Option A", "hashOfB": "Option B" },
//     results: { "Option A": 0, "Option B": 0 }, // Vote counts
//     voters: { "voterJid1": "hashOfA", "voterJid2": "hashOfB" }, // To track who voted for what (optional for preventing re-vote)
//     chatId: "original_chat_id_where_poll_was_sent",
//     timestamp: 1678886400000
//   }
// }
let activePolls = {}; // Store for polls sent in the current session

function generateOptionSha256(optionText) {
    return crypto.createHash('sha256').update(Buffer.from(optionText)).digest('hex');
}

async function connectToWhatsApp() {
    // ... (කලින් තිබූ Baileys connection logic එක එහෙමමයි)
    // फक्त logger level එක 'debug' වලට දාගන්න, poll updates හරියට එනවද බලන්න
    console.log('Initializing Baileys WhatsApp Client (Poll Focus)...');
    const { state, saveCreds } = await useMultiFileAuthState('baileys_auth_info');
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`using Baileys version ${version.join('.')}`);

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: true,
        browser: ['WhatsApp Poll Enhanced', 'Chrome', '1.0'],
        logger: pino({ level: 'debug' }) // DEBUG level to see more logs, including poll updates
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        // ... (කලින් තිබූ connection update logic එක එහෙමමයි)
        if (connection === 'open') {
            console.log('Baileys WhatsApp Client is ready! (Poll Focus)');
            clientReady = true;
            qrCodeData = null;
            io.emit('client_status', 'ready');
        } else if (connection === 'close') {
            clientReady = false;
            // ... (rest of close logic)
        }
        if (qr) {
            qrCodeData = qr;
            io.emit('qr_code', qr);
            io.emit('client_status', 'qr_pending');
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return; // Only process new messages

        const msg = messages[0];
        // console.log('Received message:', JSON.stringify(msg, undefined, 2)); // Detailed log for incoming messages

        if (msg.message && msg.message.pollUpdateMessage) {
            const pollUpdate = msg.message.pollUpdateMessage;
            const originalPollMsgKey = pollUpdate.pollCreationMessageKey;
            const voterJid = msg.key.participant || msg.key.remoteJid; // Participant in group, remoteJid in PM

            if (!originalPollMsgKey || !originalPollMsgKey.id) {
                console.warn("Poll update received without original poll message key ID. Skipping.");
                return;
            }
            const pollMsgId = originalPollMsgKey.id;

            console.log(`Poll Update for Poll ID: ${pollMsgId} from Voter: ${voterJid}`);
            // console.log('Poll Update Details:', JSON.stringify(pollUpdate, undefined, 2));


            if (activePolls[pollMsgId]) {
                const poll = activePolls[pollMsgId];
                // Assuming pollUpdate.votes contains an array of selectedOption (Buffers)
                // Each selectedOption is a SHA256 hash of the option string
                const selectedOptionHashes = pollUpdate.votes.map(vote => Buffer.from(vote.selectedOption).toString('hex'));

                // Clear previous votes from this voter for this poll before applying new ones
                // (A user can change their vote, pollUpdate usually sends all current selections)
                for (const optionText in poll.results) {
                    if (poll.voters[voterJid] && poll.optionHashes[poll.voters[voterJid]] === optionText) {
                        // This logic is a bit complex if a voter previously voted for multiple options
                        // and now changes one. Simpler: Reset this voter's previous votes if any.
                    }
                }
                // A simpler way to handle vote changes:
                // Reset counts that this voter contributed to, then add new votes.
                // This needs careful thought if a user could previously vote for multiple options
                // and now only for one, or changes their multi-vote.
                // For now, let's assume a user's new vote update replaces their old one entirely.

                // First, identify what this voter previously voted for and decrement those counts
                if (poll.voters[voterJid]) { // If voter had previous votes stored
                    const previousVoteHashes = Array.isArray(poll.voters[voterJid]) ? poll.voters[voterJid] : [poll.voters[voterJid]];
                    previousVoteHashes.forEach(prevHash => {
                        const optionText = poll.optionHashes[prevHash];
                        if (optionText && poll.results[optionText] > 0) {
                            poll.results[optionText]--;
                        }
                    });
                }

                // Update with new votes
                let votedOptionsText = [];
                selectedOptionHashes.forEach(hash => {
                    const optionText = poll.optionHashes[hash];
                    if (optionText) {
                        poll.results[optionText]++;
                        votedOptionsText.push(optionText);
                    } else {
                        console.warn(`Unknown option hash ${hash} received for poll ${pollMsgId}`);
                    }
                });
                poll.voters[voterJid] = selectedOptionHashes; // Store current vote hashes for this voter

                console.log(`Updated poll results for ${pollMsgId}:`, poll.results);
                io.emit('poll_update_to_gui', { pollMsgId: pollMsgId, results: poll.results, question: poll.question, options: poll.options });
            } else {
                console.warn(`Received poll update for an unknown or inactive poll ID: ${pollMsgId}`);
            }
        }
    });
}

connectToWhatsApp(); // Initialize connection

io.on('connection', (socket) => {
    console.log('GUI connected via Socket.IO');
    socket.emit('client_status', clientReady ? 'ready' : (qrCodeData ? 'qr_pending' : 'disconnected'));
    if (qrCodeData) socket.emit('qr_code', qrCodeData);
    // Send all current poll data to a newly connected client
    socket.emit('initial_poll_data', activePolls);
});

// API Endpoints
app.get('/status', (req, res) => res.json({ status: clientReady ? 'ready' : (qrCodeData ? 'qr_pending' : 'disconnected'), qrCode: qrCodeData }));

app.post('/send-poll', async (req, res) => {
    if (!clientReady || !sock) return res.status(400).json({ success: false, message: 'Baileys client not ready.' });

    const { chatId, question, options, allowMultipleAnswers } = req.body; // allowMultipleAnswers from app.py

    if (!chatId || !question || !options || !Array.isArray(options) || options.length < 1) { // Poll needs at least 1 option
        return res.status(400).json({ success: false, message: 'chatId, question, and at least one option required.' });
    }
    if (options.length > 12) { // WhatsApp limit for poll options
        return res.status(400).json({ success: false, message: 'Maximum of 12 poll options allowed.' });
    }


    try {
        await delay(500 + Math.random() * 1000);

        const pollMessage = {
            name: question,
            values: options,
            selectableCount: allowMultipleAnswers ? 0 : 1, // 0 for multiple, 1 for single
        };

        const sentMsg = await sock.sendMessage(chatId, { poll: pollMessage });
        const pollMsgId = sentMsg.key.id;

        // Store poll info for tracking results
        const optionHashes = {};
        const initialResults = {};
        options.forEach(opt => {
            optionHashes[generateOptionSha256(opt)] = opt;
            initialResults[opt] = 0;
        });

        activePolls[pollMsgId] = {
            question: question,
            options: options,
            optionHashes: optionHashes,
            results: initialResults,
            voters: {},
            chatId: chatId,
            timestamp: Date.now(),
            selectableCount: pollMessage.selectableCount
        };

        console.log(`Poll sent successfully to ${chatId}, Msg ID: ${pollMsgId}`);
        console.log("Active Polls:", activePolls);
        io.emit('new_poll_sent', activePolls[pollMsgId]); // Inform GUI about the new poll for the results tab
        res.json({ success: true, message: 'Poll sent successfully!', pollMsgId: pollMsgId });

    } catch (error) {
        console.error('Error sending poll:', error);
        res.status(500).json({ success: false, message: 'Failed to send poll.', error: error.message });
    }
});

app.get('/get-chats', async (req, res) => {
    // ... (කලින් තිබූ /get-chats logic එක එහෙමමයි, template sender එකට අදාළ නැති නිසා)
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
        if (sock.contacts) {
            for (const contact of Object.values(sock.contacts)) {
                if (contact.id && contact.id.endsWith('@s.whatsapp.net') && !contact.id.includes('@g.us') && contact.name) {
                    if (!simplifiedChats.some(c => c.id === contact.id)) {
                        simplifiedChats.push({ id: contact.id, name: contact.name, isGroup: false });
                    }
                }
            }
        }
        simplifiedChats.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
        res.json({ success: true, chats: simplifiedChats });
    } catch (error) {
        console.error('Error fetching chats:', error);
        res.status(500).json({ success: false, message: 'Failed to fetch chats.', error: error.message });
    }
});

app.post('/logout', async (req, res) => {
    // ... (කලින් තිබූ /logout logic එක එහෙමමයි)
    console.log('Received logout request.');
    if (sock) {
        try {
            await sock.logout();
            console.log('Baileys client logged out successfully.');
        } catch (error) { console.error('Error during Baileys logout:', error); }
        finally {
            const sessionPath = path.join(__dirname, 'baileys_auth_info');
            try { await fs.rm(sessionPath, { recursive: true, force: true }); console.log('Session folder "baileys_auth_info" deleted.'); }
            catch (err) { console.error('Error deleting session folder:', err); }
            clientReady = false; qrCodeData = null; activePolls = {}; // Clear active polls on logout
            io.emit('client_status', 'disconnected'); io.emit('all_polls_data', activePolls); // Send empty polls
            res.json({ success: true, message: 'Logged out and session cleared.' });
        }
    } else { /* ... */ res.status(400).json({ success: false, message: 'Client not active.' });}
});

// New endpoint to get all poll data
app.get('/get-all-poll-data', (req, res) => {
    res.json({ success: true, polls: activePolls });
});


server.listen(PORT, () => {
    console.log(`Node.js server (Poll Focus) listening on port ${PORT}`);
});