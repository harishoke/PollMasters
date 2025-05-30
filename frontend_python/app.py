import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk, simpledialog
from PIL import Image, ImageTk
import requests
import socketio
import threading
import time
import random
import json
import os

# --- Configuration ---
NODE_SERVER_URL = "http://localhost:3000"
NODE_API_STATUS = f"{NODE_SERVER_URL}/status"
NODE_API_QR = f"{NODE_SERVER_URL}/qr"
NODE_API_SEND_POLL = f"{NODE_SERVER_URL}/send-poll"
NODE_API_GET_CHATS = f"{NODE_SERVER_URL}/get-chats"
NODE_API_LOGOUT = f"{NODE_SERVER_URL}/logout"
NODE_API_GET_ALL_POLL_DATA = f"{NODE_SERVER_URL}/get-all-poll-data" # New API

TEMPLATES_FILE = "poll_templates.json"

# --- Global Variables ---
sio_connected = False
chat_mapping = {}
active_polls_data_from_server = {} # To store poll data received from server

# --- Socket.IO Client ---
sio = socketio.Client(reconnection_attempts=5, reconnection_delay=3)

@sio.event
def connect():
    global sio_connected
    sio_connected = True; print('Socket.IO connected!')
    if 'status_label' in globals() and status_label.winfo_exists():
        update_status_label("Connected to Node.js.", "blue"); check_whatsapp_status()

@sio.event
def connect_error(data):
    global sio_connected; sio_connected = False; print(f"Socket.IO connection failed: {data}")
    if 'status_label' in globals() and status_label.winfo_exists(): update_status_label(f"Socket.IO conn error.", "red")

@sio.event
def disconnect():
    global sio_connected; sio_connected = False; print('Socket.IO disconnected.')
    if 'status_label' in globals() and status_label.winfo_exists():
        update_status_label("Disconnected from Node.js.", "orange")
        if 'qr_display_label' in globals() and qr_display_label.winfo_exists(): qr_display_label.config(image='', text="QR Code")
        if 'poll_chat_listbox' in globals() and poll_chat_listbox.winfo_exists(): poll_chat_listbox.delete(0, tk.END)
        if 'poll_results_listbox' in globals() and poll_results_listbox.winfo_exists(): poll_results_listbox.delete(0, tk.END); poll_results_display_text.set("Select a poll to see results.")


@sio.event
def qr_code(qr):
    print(f"Received QR Code.")
    if 'qr_display_label' in globals() and qr_display_label.winfo_exists():
        display_qr_code(qr); update_status_label("Scan QR code.", "red")
        if 'notebook' in globals() and 'connection_tab' in globals(): notebook.select(connection_tab)

@sio.event
def client_status(status):
    print(f"WhatsApp Client Status: {status}")
    if 'status_label' in globals() and status_label.winfo_exists():
        if status == 'ready':
            update_status_label("WhatsApp Client is READY!", "green")
            if 'qr_display_label' in globals() and qr_display_label.winfo_exists(): qr_display_label.config(image='', text="WhatsApp Client READY!")
            fetch_chats()
            fetch_all_poll_data_from_server() # Fetch initial poll data
        elif status == 'qr_pending': # ... (as before)
            update_status_label("Waiting for QR scan...", "orange")
        elif status in ['disconnected', 'auth_failure']: # ... (as before, clear relevant lists)
            update_status_label(f"WhatsApp: {status}. Please connect.", "red")
            if 'poll_chat_listbox' in globals() and poll_chat_listbox.winfo_exists(): poll_chat_listbox.delete(0, tk.END)
            if 'poll_results_listbox' in globals() and poll_results_listbox.winfo_exists(): poll_results_listbox.delete(0, tk.END); poll_results_display_text.set("Select a poll.")


# Listen for poll updates from server
@sio.event
def poll_update_to_gui(data):
    global active_polls_data_from_server
    print(f"GUI received poll_update_to_gui: {data}")
    poll_msg_id = data.get('pollMsgId')
    if poll_msg_id and poll_msg_id in active_polls_data_from_server:
        active_polls_data_from_server[poll_msg_id]['results'] = data.get('results', {})
        # If this poll is currently selected in the results tab, refresh its display
        if 'poll_results_listbox' in globals() and poll_results_listbox.winfo_exists():
            try:
                selected_indices = poll_results_listbox.curselection()
                if selected_indices:
                    selected_poll_q_with_id = poll_results_listbox.get(selected_indices[0])
                    # Extract msg_id from "Question (ID: msg_id)"
                    if f"(ID: {poll_msg_id})" in selected_poll_q_with_id:
                        display_selected_poll_results() # Refresh display
            except Exception as e:
                print(f"Error updating selected poll display: {e}")
        update_status_label(f"Poll '{active_polls_data_from_server[poll_msg_id].get('question', poll_msg_id)}' updated!", "cyan")

@sio.event
def new_poll_sent(poll_data): # When a new poll is sent by this client (or another, if server broadcasts)
    global active_polls_data_from_server
    print(f"GUI received new_poll_sent: {poll_data}")
    # Assuming poll_data is the full data for one poll, keyed by its msgId in server
    # For now, let's assume server sends the pollMsgId as a key and poll_data is its value
    # However, the server code sends the poll object directly. We need its ID.
    # For simplicity, let's refetch all polls or expect server to send ID with data.
    # The server.js 'new_poll_sent' emits the poll object. We need its ID.
    # Let's modify server to send { pollMsgId: activePolls[pollMsgId] }
    # OR find the ID from poll_data if it's included by server (it should be for matching)

    # Assuming server sends poll_data that includes its own pollMsgId (e.g. as a top level key)
    # Or, we can just refetch all data for simplicity on new poll.
    # Let's rely on `initial_poll_data` and manual refresh for now, or enhance `new_poll_sent` event from server.
    # For now:
    fetch_all_poll_data_from_server() # Easiest way to update the list
    update_status_label(f"New poll '{poll_data.get('question', 'N/A')}' available in results tab.", "magenta")

@sio.event
def initial_poll_data(data): # When GUI connects, server sends all current poll data
    global active_polls_data_from_server
    print("GUI received initial_poll_data")
    active_polls_data_from_server = data if data else {}
    populate_poll_results_listbox()
    update_status_label(f"Loaded {len(active_polls_data_from_server)} existing polls.", "info")


# --- GUI Functions ---
def update_status_label(message, color="blue"): # ... (as before)
    if 'status_label' in globals() and status_label.winfo_exists():
        status_label.config(text=f"Status: {message}", fg=color)
        if 'root' in globals() and root.winfo_exists(): root.update_idletasks()

def check_whatsapp_status(): # ... (as before)
    if 'status_label' not in globals() or not status_label.winfo_exists(): return
    update_status_label("Checking WhatsApp status...", "blue")
    # ... (rest of the function as in previous corrected version) ...
    try:
        response = requests.get(NODE_API_STATUS, timeout=5)
        response.raise_for_status()
        data = response.json()
        current_qr = data.get('qrCode')
        current_status = data.get('status')
        if not sio_connected and current_status: client_status(current_status)
        if current_qr and current_status == 'qr_pending':
            if 'qr_display_label' in globals() and qr_display_label.winfo_exists(): display_qr_code(current_qr)
        elif current_status == 'ready':
             if 'qr_display_label' in globals() and qr_display_label.winfo_exists(): qr_display_label.config(image='', text="WhatsApp Client is connected and ready!")
    except Exception as e: update_status_label(f"Error checking status: {e}", "red")


def display_qr_code(qr_data): # ... (as before, ensure Pillow is used)
    if 'qr_display_label' not in globals() or not qr_display_label.winfo_exists(): return
    try:
        import qrcode
        from PIL import Image, ImageTk # Ensure Pillow is imported here too
        img = qrcode.make(qr_data)
        if not hasattr(img, 'resize'):
            qr_code_obj = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
            qr_code_obj.add_data(qr_data); qr_code_obj.make(fit=True)
            img = qr_code_obj.make_image(fill_color="black", back_color="white").convert('RGB')
        img_resized = img.resize((250, 250), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img_resized)
        qr_display_label.config(image=photo, text=""); qr_display_label.image = photo
    except Exception as e: update_status_label(f"Error QR display: {e}", "red"); print(f"QR display error: {e}")


def fetch_chats(): # ... (as before, ensures only poll_chat_listbox is updated if template listbox is removed)
    global chat_mapping
    if 'status_label' not in globals() or not status_label.winfo_exists(): return
    update_status_label("Fetching chats...", "blue")
    try:
        response = requests.get(NODE_API_GET_CHATS, timeout=10); response.raise_for_status(); data = response.json()
        if data.get('success'):
            listboxes_to_update = []
            if 'poll_chat_listbox' in globals() and poll_chat_listbox.winfo_exists(): listboxes_to_update.append(poll_chat_listbox)
            # Removed template_chat_listbox handling

            for lb in listboxes_to_update: lb.delete(0, tk.END)
            chat_mapping.clear(); fetched_chats_count = 0
            if 'chats' in data and data['chats'] is not None:
                for chat in data['chats']:
                    display_name = f"{chat.get('name', 'Unknown')} ({'Group' if chat.get('isGroup') else 'Contact'})"
                    chat_id_val = chat.get('id')
                    if chat_id_val:
                        chat_mapping[display_name] = chat_id_val
                        for lb in listboxes_to_update: lb.insert(tk.END, display_name)
                        fetched_chats_count +=1
            update_status_label(f"Fetched {fetched_chats_count} chats.", "green")
        else: update_status_label(f"Failed fetch chats: {data.get('message')}", "red")
    except Exception as e: update_status_label(f"Error fetch chats: {e}", "red"); print(f"Fetch chats error: {e}")


# --- Poll Sender Functions ---
def send_poll_message():
    if 'poll_question_entry' not in globals(): return
    question = poll_question_entry.get().strip()
    options = list(poll_options_listbox.get(0, tk.END))
    selected_indices = poll_chat_listbox.curselection()
    allow_multiple = allow_multiple_answers_var.get() # Get value from checkbox

    if not question: messagebox.showerror("Error", "Poll question empty."); return
    if not options or len(options) < 1: messagebox.showerror("Error", "Min 1 poll option."); return # WhatsApp allows 1 option polls
    if len(options) > 12: messagebox.showerror("Error", "Max 12 poll options."); return
    if not selected_indices: messagebox.showerror("Error", "Select chat(s)."); return

    selected_chat_ids = [chat_mapping[poll_chat_listbox.get(i)] for i in selected_indices]
    if not selected_chat_ids: messagebox.showerror("Error", "No valid chats selected."); return
    if not messagebox.askyesno("Confirm", f"Send poll to {len(selected_chat_ids)} chats?"): return

    update_status_label("Sending poll...", "blue")
    # Pass allow_multiple to the threaded function
    threading.Thread(target=_send_polls_threaded, args=(selected_chat_ids, question, options, allow_multiple), daemon=True).start()

def _send_polls_threaded(chat_ids, question, options, allow_multiple): # Added allow_multiple
    for chat_id in chat_ids:
        try:
            # Add allowMultipleAnswers to payload
            payload = {"chatId": chat_id, "question": question, "options": options, "allowMultipleAnswers": allow_multiple}
            response = requests.post(NODE_API_SEND_POLL, json=payload, timeout=10)
            response.raise_for_status(); result = response.json()
            if result.get('success'):
                update_status_label(f"Poll sent to {chat_id}!", "green")
                # After sending, server will emit 'new_poll_sent', GUI will catch it
                # Or we can call fetch_all_poll_data_from_server() here too after a small delay
            else: update_status_label(f"Failed poll to {chat_id}: {result.get('message', 'Unknown')}", "red")
            time.sleep(random.uniform(anti_ban_delay_min.get(), anti_ban_delay_max.get()))
        except Exception as e: update_status_label(f"Error poll to {chat_id}: {e}", "red")
    update_status_label("Finished sending polls.", "blue")

# ... (add_poll_option, edit_poll_option, delete_poll_option, clear_poll_options as before) ...
def add_poll_option():
    option = poll_option_entry.get().strip()
    if option and option not in poll_options_listbox.get(0, tk.END):
        poll_options_listbox.insert(tk.END, option); poll_option_entry.delete(0, tk.END)
    else: messagebox.showinfo("Add Option", "Enter a non-empty or unique option.")
def edit_poll_option():
    selected = poll_options_listbox.curselection()
    if not selected: messagebox.showinfo("Edit Option", "Select an option to edit."); return
    idx = selected[0]; current_val = poll_options_listbox.get(idx)
    new_val = simpledialog.askstring("Edit Option", "Edit:", initialvalue=current_val)
    if new_val and new_val.strip() and new_val.strip() != current_val:
        if new_val.strip() in poll_options_listbox.get(0, tk.END): messagebox.showinfo("Edit Option", "Option already exists."); return
        poll_options_listbox.delete(idx); poll_options_listbox.insert(idx, new_val.strip())
def delete_poll_option():
    selected = poll_options_listbox.curselection()
    if selected: poll_options_listbox.delete(selected[0])
    else: messagebox.showinfo("Delete Option", "Select an option to delete.")
def clear_poll_options(): poll_options_listbox.delete(0, tk.END)


# --- Poll Template Management --- (as before)
def load_poll_templates(): # ... (as before)
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except json.JSONDecodeError: return {}
    return {}
def save_poll_templates(data): # ... (as before)
    with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
def update_poll_template_dropdown(): # ... (as before)
    if 'poll_template_combobox' not in globals() or not poll_template_combobox.winfo_exists(): return
    templates = load_poll_templates(); names = list(templates.keys())
    poll_template_combobox['values'] = names
    if names: poll_template_combobox.set(names[0])
    else: poll_template_combobox.set("")
def save_current_poll_as_template(): # ... (as before)
    q = poll_question_entry.get().strip(); opts = list(poll_options_listbox.get(0, tk.END))
    if not q and not opts: messagebox.showinfo("Save", "Enter question or options."); return
    name = simpledialog.askstring("Save Poll Template", "Template name:")
    if name:
        templates = load_poll_templates(); templates[name] = {"question": q, "options": "\n".join(opts)}
        save_poll_templates(templates); update_poll_template_dropdown(); messagebox.showinfo("Save", f"'{name}' saved!")
def load_selected_poll_template(event=None): # ... (as before)
    name = poll_template_combobox.get(); templates = load_poll_templates()
    if name in templates:
        t = templates[name]; poll_question_entry.delete(0, tk.END); poll_question_entry.insert(0, t.get("question", ""))
        clear_poll_options();
        for opt in t.get("options", "").split('\n'):
            if opt.strip(): poll_options_listbox.insert(tk.END, opt.strip())
        update_status_label(f"Poll template '{name}' loaded.", "blue")
def delete_selected_poll_template(): # ... (as before)
    name = poll_template_combobox.get()
    if not name: messagebox.showinfo("Delete", "Select template."); return
    if messagebox.askyesno("Delete", f"Delete '{name}'?"):
        templates = load_poll_templates()
        if name in templates: del templates[name]; save_poll_templates(templates); update_poll_template_dropdown(); messagebox.showinfo("Delete", f"'{name}' deleted.")


# --- Poll Results Functions ---
def fetch_all_poll_data_from_server():
    global active_polls_data_from_server
    if not sio_connected: # Only fetch if connected, or rely on initial_poll_data
        # update_status_label("Not connected to fetch poll data.", "orange")
        # return # Or try to fetch anyway
        pass # Allow attempt even if socket flag is false, HTTP might work

    update_status_label("Fetching all poll data...", "blue")
    try:
        response = requests.get(NODE_API_GET_ALL_POLL_DATA, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('success'):
            active_polls_data_from_server = data.get('polls', {})
            populate_poll_results_listbox()
            update_status_label(f"Fetched {len(active_polls_data_from_server)} polls for results.", "green")
        else:
            update_status_label(f"Failed to fetch poll data: {data.get('message')}", "red")
    except Exception as e:
        update_status_label(f"Error fetching poll data: {e}", "red")
        print(f"Error fetching poll data: {e}")


def populate_poll_results_listbox():
    if 'poll_results_listbox' not in globals() or not poll_results_listbox.winfo_exists(): return
    poll_results_listbox.delete(0, tk.END)
    if not active_polls_data_from_server:
        poll_results_listbox.insert(tk.END, "No polls sent in this session yet.")
        return

    # Sort polls by timestamp, newest first if available
    sorted_poll_ids = sorted(active_polls_data_from_server.keys(),
                             key=lambda pid: active_polls_data_from_server[pid].get('timestamp', 0),
                             reverse=True)

    for poll_msg_id in sorted_poll_ids:
        poll_info = active_polls_data_from_server[poll_msg_id]
        # Display question and part of ID for uniqueness in Listbox
        display_text = f"{poll_info.get('question', 'Unknown Poll')} (ID: ...{poll_msg_id[-6:]})"
        poll_results_listbox.insert(tk.END, display_text)

def display_selected_poll_results(event=None):
    if 'poll_results_listbox' not in globals() or not poll_results_listbox.winfo_exists(): return
    selected_indices = poll_results_listbox.curselection()
    if not selected_indices:
        poll_results_display_text.set("Select a poll from the list to see its results.")
        return

    selected_item_text = poll_results_listbox.get(selected_indices[0])
    # Extract poll_msg_id from the listbox text "Question (ID: ...xxxxxx)"
    try:
        poll_msg_id_suffix = selected_item_text.split('(ID: ...')[-1][:-1] # Get 'xxxxxx'
        # Find the full poll_msg_id
        actual_poll_msg_id = None
        for pid in active_polls_data_from_server.keys():
            if pid.endswith(poll_msg_id_suffix):
                actual_poll_msg_id = pid
                break
        
        if not actual_poll_msg_id or actual_poll_msg_id not in active_polls_data_from_server:
            poll_results_display_text.set("Error: Could not find poll data for selection.")
            return
    except Exception:
        poll_results_display_text.set("Error parsing selected poll ID.")
        return


    poll_info = active_polls_data_from_server.get(actual_poll_msg_id)
    if not poll_info:
        poll_results_display_text.set("Poll data not found for this ID.")
        return

    results_str = f"Poll Question: {poll_info.get('question', 'N/A')}\n"
    results_str += f"Message ID: {actual_poll_msg_id}\n"
    results_str += f"Timestamp: {time.ctime(poll_info.get('timestamp', 0)/1000) if poll_info.get('timestamp') else 'N/A'}\n"
    results_str += "------------------------------------\nResults:\n"

    poll_results = poll_info.get('results', {})
    original_options = poll_info.get('options', [])

    # Display results in the order of original options
    total_votes = sum(poll_results.values())
    for option_text in original_options:
        votes = poll_results.get(option_text, 0)
        percentage = (votes / total_votes * 100) if total_votes > 0 else 0
        results_str += f"  - {option_text}: {votes} votes ({percentage:.1f}%)\n"

    results_str += f"------------------------------------\nTotal Votes Cast: {total_votes}\n"
    
    # Who voted for what (optional, can be long)
    # voters_info = poll_info.get('voters', {})
    # if voters_info:
    #     results_str += "\nVoter Details (Advanced):\n"
    #     for voter_jid, voted_option_hashes in voters_info.items():
    #         option_texts_voted = [poll_info['optionHashes'].get(h, "Unknown Option") for h in voted_option_hashes]
    #         results_str += f"  - {voter_jid} voted for: {', '.join(option_texts_voted)}\n"


    poll_results_display_text.set(results_str)


# --- Logout Function --- (as before)
def logout_and_reconnect():
    if messagebox.askyesno("Logout & Connect New", "Logout from current WhatsApp and connect a new one? This clears session data."):
        update_status_label("Logging out...", "orange"); threading.Thread(target=_logout_threaded, daemon=True).start()
def _logout_threaded():
    global active_polls_data_from_server # Clear local poll data on logout
    try:
        response = requests.post(NODE_API_LOGOUT, timeout=10); response.raise_for_status(); result = response.json()
        if result.get('success'):
            messagebox.showinfo("Logout", result.get('message', "Logged out."))
            update_status_label("Logged out. Click 'Check Status / Connect'.", "blue")
            active_polls_data_from_server = {} # Clear local cache
            if 'qr_display_label' in globals() and qr_display_label.winfo_exists(): qr_display_label.config(image='', text="QR Code")
            if 'poll_chat_listbox' in globals() and poll_chat_listbox.winfo_exists(): poll_chat_listbox.delete(0, tk.END)
            if 'poll_results_listbox' in globals() and poll_results_listbox.winfo_exists(): poll_results_listbox.delete(0, tk.END); poll_results_display_text.set("Logged out.")
        else: messagebox.showerror("Logout Error", result.get('message', "Failed to logout.")); update_status_label(f"Logout failed: {result.get('message')}", "red")
    except Exception as e: messagebox.showerror("Logout Error", f"An error occurred: {e}"); update_status_label(f"Logout error: {e}", "red")


# --- GUI Setup ---
root = tk.Tk()
root.title("WhatsApp Poll Master")
root.geometry("900x750") # Adjusted size

status_label = tk.Label(root, text="Status: Initializing...", bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("Arial", 10))
status_label.pack(side=tk.BOTTOM, fill=tk.X, ipady=2)
main_frame = tk.Frame(root, padx=10, pady=10); main_frame.pack(fill=tk.BOTH, expand=True)
notebook = ttk.Notebook(main_frame); notebook.pack(fill=tk.BOTH, expand=True)

# == Connection Tab == (as before)
connection_tab = ttk.Frame(notebook); notebook.add(connection_tab, text="🔌 Connection")
connection_tab.columnconfigure(0, weight=1); connection_tab.rowconfigure(1, weight=1)
tk.Label(connection_tab, text="WhatsApp Connection", font=("Arial", 14, "bold")).grid(row=0, column=0, pady=(10,5), sticky="ew")
qr_display_label = tk.Label(connection_tab, text="QR Code will appear here", bg="lightgrey", relief=tk.SUNKEN, height=12)
qr_display_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
connection_button_frame = tk.Frame(connection_tab)
connection_button_frame.grid(row=2, column=0, pady=10)
tk.Button(connection_button_frame, text="Check Status / Connect", command=check_whatsapp_status, font=("Arial", 10, "bold"), bg="#28A745", fg="white").pack(side=tk.LEFT, padx=5, ipady=2)
tk.Button(connection_button_frame, text="Refresh Chats", command=fetch_chats, font=("Arial", 10, "bold"), bg="#17A2B8", fg="white").pack(side=tk.LEFT, padx=5, ipady=2)
tk.Button(connection_button_frame, text="Logout / New Account", command=logout_and_reconnect, font=("Arial", 10, "bold"), bg="#DC3545", fg="white").pack(side=tk.LEFT, padx=5, ipady=2)


# == Poll Sender Tab == (Added "Allow Multiple Answers" checkbox)
poll_sender_tab = ttk.Frame(notebook); notebook.add(poll_sender_tab, text="📊 Poll Sender")
# ... (Poll Template section as before) ...
poll_template_frame = ttk.LabelFrame(poll_sender_tab, text="Poll Templates", padding=10)
poll_template_frame.pack(fill=tk.X, padx=10, pady=(10,5))
poll_template_combobox = ttk.Combobox(poll_template_frame, state="readonly", width=35, font=("Arial", 9))
poll_template_combobox.pack(side=tk.LEFT, padx=5, pady=5); poll_template_combobox.bind("<<ComboboxSelected>>", load_selected_poll_template)
ptb_frame = tk.Frame(poll_template_frame); ptb_frame.pack(side=tk.LEFT, padx=5)
tk.Button(ptb_frame, text="Load", command=load_selected_poll_template, width=6).pack(side=tk.LEFT, padx=2)
tk.Button(ptb_frame, text="Save", command=save_current_poll_as_template, width=6).pack(side=tk.LEFT, padx=2)
tk.Button(ptb_frame, text="Delete", command=delete_selected_poll_template, width=6).pack(side=tk.LEFT, padx=2)

tk.Label(poll_sender_tab, text="Select Chats/Groups for Poll", font=("Arial", 9, "bold")).pack(pady=(8,2))
poll_chat_listbox_frame = tk.Frame(poll_sender_tab)
poll_chat_listbox_frame.pack(fill=tk.X, padx=10, pady=2)
poll_chat_listbox_scrollbar = tk.Scrollbar(poll_chat_listbox_frame, orient=tk.VERTICAL)
poll_chat_listbox = tk.Listbox(poll_chat_listbox_frame, selectmode=tk.MULTIPLE, yscrollcommand=poll_chat_listbox_scrollbar.set, exportselection=False, font=("Arial", 9), height=5)
poll_chat_listbox_scrollbar.config(command=poll_chat_listbox.yview); poll_chat_listbox_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
poll_chat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

tk.Label(poll_sender_tab, text="Poll Question:", anchor=tk.W, font=("Arial", 9)).pack(fill=tk.X, padx=10, pady=(8,0))
poll_question_entry = tk.Entry(poll_sender_tab, width=50, font=("Arial", 10)); poll_question_entry.pack(fill=tk.X, padx=10, pady=2)

# Allow Multiple Answers Checkbox
allow_multiple_answers_var = tk.BooleanVar(value=False) # Default to single answer
allow_multiple_checkbox = ttk.Checkbutton(poll_sender_tab, text="Allow multiple answers (select 0 for this in Baileys)", variable=allow_multiple_answers_var)
allow_multiple_checkbox.pack(padx=10, pady=2, anchor=tk.W)


pom_frame = ttk.LabelFrame(poll_sender_tab, text="Poll Options (1-12 options)", padding=5)
pom_frame.pack(fill=tk.X, padx=10, pady=5)
poll_option_entry = tk.Entry(pom_frame, width=30, font=("Arial", 10)); poll_option_entry.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
pob_frame = tk.Frame(pom_frame)
pob_frame.pack(side=tk.LEFT, padx=5)
for text, cmd in [("Add", add_poll_option), ("Edit", edit_poll_option), ("Del", delete_poll_option), ("Clear", clear_poll_options)]:
    tk.Button(pob_frame, text=text, command=cmd, width=5).pack(side=tk.LEFT, padx=1)
poll_options_listbox_outer_frame = tk.Frame(poll_sender_tab)
poll_options_listbox_outer_frame.pack(fill=tk.X, padx=10, pady=5)
poll_options_listbox = tk.Listbox(poll_options_listbox_outer_frame, height=4, font=("Arial", 9))
poll_options_listbox.pack(fill=tk.BOTH, expand=True)

anti_ban_frame = ttk.LabelFrame(poll_sender_tab, text="Anti-Ban Settings", padding=5) # ... (as before)
anti_ban_frame.pack(fill=tk.X, padx=10, pady=5, ipady=2)
anti_ban_delay_min = tk.DoubleVar(value=2.5); anti_ban_delay_max = tk.DoubleVar(value=5.5)
tk.Label(anti_ban_frame, text="Min (s):", font=("Arial",9)).pack(side=tk.LEFT, padx=(5,0))
ttk.Entry(anti_ban_frame, textvariable=anti_ban_delay_min, width=5, font=("Arial",9)).pack(side=tk.LEFT, padx=(0,5))
tk.Label(anti_ban_frame, text="Max (s):", font=("Arial",9)).pack(side=tk.LEFT, padx=(5,0))
ttk.Entry(anti_ban_frame, textvariable=anti_ban_delay_max, width=5, font=("Arial",9)).pack(side=tk.LEFT, padx=(0,5))
tk.Button(poll_sender_tab, text="Send Poll", command=send_poll_message, font=("Arial", 12, "bold"), bg="#4CAF50", fg="white").pack(pady=10, ipadx=10, ipady=5)


# == Poll Results Tab (New) ==
poll_results_tab = ttk.Frame(notebook)
notebook.add(poll_results_tab, text="📈 Poll Results")

# Frame for listing polls and refreshing
poll_list_management_frame = tk.Frame(poll_results_tab)
poll_list_management_frame.pack(fill=tk.X, padx=10, pady=5)
tk.Label(poll_list_management_frame, text="Sent Polls (Newest First):", font=("Arial", 10, "bold")).pack(side=tk.LEFT, anchor=tk.W)
refresh_polls_button = tk.Button(poll_list_management_frame, text="🔄 Refresh Poll List/Results", command=fetch_all_poll_data_from_server, bg="#007BFF", fg="white")
refresh_polls_button.pack(side=tk.RIGHT, padx=5)

poll_results_listbox_frame = tk.Frame(poll_results_tab)
poll_results_listbox_frame.pack(fill=tk.X, padx=10, pady=5)
poll_results_listbox_scrollbar = tk.Scrollbar(poll_results_listbox_frame, orient=tk.VERTICAL)
poll_results_listbox = tk.Listbox(poll_results_listbox_frame, yscrollcommand=poll_results_listbox_scrollbar.set, exportselection=False, font=("Arial", 9), height=8)
poll_results_listbox_scrollbar.config(command=poll_results_listbox.yview)
poll_results_listbox_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
poll_results_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
poll_results_listbox.bind("<<ListboxSelect>>", display_selected_poll_results)

# Frame for displaying results of the selected poll
poll_results_display_frame = ttk.LabelFrame(poll_results_tab, text="Selected Poll Details & Results", padding=10)
poll_results_display_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

poll_results_display_text = tk.StringVar()
poll_results_display_text.set("Select a poll from the list above to see its results.")
poll_results_label = scrolledtext.ScrolledText(poll_results_display_frame, wrap=tk.WORD, font=("Courier New", 10), state=tk.NORMAL, relief=tk.SOLID, borderwidth=1, height=15)
# Bind StringVar to ScrolledText content (requires a bit more work than simple Label)
# For ScrolledText, we'll update it directly.
poll_results_label.pack(fill=tk.BOTH, expand=True)
# Initial population of the ScrolledText (cannot use textvariable directly with ScrolledText)
poll_results_label.delete('1.0', tk.END)
poll_results_label.insert('1.0', "Select a poll from the list above to see its results.")
poll_results_label.config(state=tk.DISABLED) # Make it read-only after inserting

# Modify display_selected_poll_results to update ScrolledText
def display_selected_poll_results(event=None): # Overwrite the previous one
    if 'poll_results_listbox' not in globals() or not poll_results_listbox.winfo_exists(): return
    selected_indices = poll_results_listbox.curselection()

    poll_results_label.config(state=tk.NORMAL) # Enable editing
    poll_results_label.delete('1.0', tk.END) # Clear previous content

    if not selected_indices:
        poll_results_label.insert('1.0', "Select a poll from the list to see its results.")
        poll_results_label.config(state=tk.DISABLED); return

    selected_item_text = poll_results_listbox.get(selected_indices[0])
    actual_poll_msg_id = None
    try:
        if "(ID: ..." in selected_item_text and selected_item_text.endswith(")"):
            poll_msg_id_suffix = selected_item_text.split('(ID: ...')[-1][:-1]
            for pid in active_polls_data_from_server.keys():
                if pid.endswith(poll_msg_id_suffix): actual_poll_msg_id = pid; break
        if not actual_poll_msg_id: raise ValueError("Could not extract ID")
    except Exception as e:
        print(f"Error parsing poll ID from listbox: {e}")
        poll_results_label.insert('1.0', "Error parsing selected poll ID from listbox item.");
        poll_results_label.config(state=tk.DISABLED); return

    poll_info = active_polls_data_from_server.get(actual_poll_msg_id)
    if not poll_info:
        poll_results_label.insert('1.0', "Poll data not found for this ID.");
        poll_results_label.config(state=tk.DISABLED); return

    results_str = f"Poll Question: {poll_info.get('question', 'N/A')}\n"
    results_str += f"Message ID: {actual_poll_msg_id}\n"
    ts = poll_info.get('timestamp')
    results_str += f"Sent on: {time.ctime(ts/1000) if ts else 'N/A'}\n"
    results_str += f"Allows Multiple Answers: {'Yes' if poll_info.get('selectableCount') == 0 else 'No (Single Choice)'}\n"
    results_str += "------------------------------------\nResults:\n"

    poll_option_results = poll_info.get('results', {})
    original_options = poll_info.get('options', [])
    total_votes = sum(poll_option_results.values())

    for option_text in original_options:
        votes = poll_option_results.get(option_text, 0)
        percentage = (votes / total_votes * 100) if total_votes > 0 else 0
        results_str += f"  - \"{option_text}\": {votes} votes ({percentage:.1f}%)\n"
    results_str += f"------------------------------------\nTotal Unique Voters Participated: {len(poll_info.get('voters', {}))}\n" # Number of unique JIDs that voted
    results_str += f"Total Votes Recorded (can be > voters if multiple choice allowed and voter changed vote): {total_votes}\n"


    poll_results_label.insert('1.0', results_str)
    poll_results_label.config(state=tk.DISABLED) # Make it read-only again


# --- Initializations --- (as before, ensure they are called after root.mainloop if needed by GUI elements)
def connect_sio_on_startup():
    while True:
        if not sio.connected:
            try:
                print("Attempting to connect to Socket.IO server (Poll Master)...")
                sio.connect(NODE_SERVER_URL, wait_timeout=10)
            except socketio.exceptions.ConnectionError as e:
                print(f"Socket.IO connection attempt failed: {e}. Will retry...")
            except Exception as e:
                print(f"Unexpected error during Socket.IO connect: {e}. Will retry...")
        time.sleep(5)
threading.Thread(target=connect_sio_on_startup, daemon=True).start()

if root.winfo_exists():
    root.after(500, check_whatsapp_status)
    root.after(600, update_poll_template_dropdown)
    # root.after(700, fetch_all_poll_data_from_server) # Fetch initial poll data (also called on 'ready')

def on_closing(): # ... (as before)
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        if sio.connected: print("Disconnecting Socket.IO..."); sio.disconnect()
        root.destroy(); print("Application closed.")
root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()