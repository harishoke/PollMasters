import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk, simpledialog
from PIL import Image, ImageTk # Ensure Pillow is available
import requests
import socketio
import threading
import time
import random # For anti-ban delay
import json
import os
import qrcode # For QR code generation

# --- Configuration ---
APP_VERSION = "1.1.0"  # Application Version
NODE_SERVER_URL = "http://localhost:3000"
NODE_API_STATUS = f"{NODE_SERVER_URL}/status"
# NODE_API_QR = f"{NODE_SERVER_URL}/qr" # Not used if QR comes via socket
NODE_API_SEND_POLL = f"{NODE_SERVER_URL}/send-poll"
NODE_API_GET_CHATS = f"{NODE_SERVER_URL}/get-chats"
NODE_API_LOGOUT = f"{NODE_SERVER_URL}/logout"
NODE_API_GET_ALL_POLL_DATA = f"{NODE_SERVER_URL}/get-all-poll-data"

TEMPLATES_FILE = "poll_templates.json"

# --- Global Variables ---
sio_connected = False
chat_mapping = {} # Stores display_name -> chat_id
active_polls_data_from_server = {} # Stores {poll_msg_id: poll_data_object}
whatsapp_client_actually_ready = False # අලුතින් එකතු කළ flag එක

# --- Socket.IO Client ---
sio = socketio.Client(reconnection_attempts=10, reconnection_delay=3, logger=False, engineio_logger=False) # Added logger flags

@sio.event
def connect():
    global sio_connected
    sio_connected = True
    print('Socket.IO connected!')
    if 'status_label' in globals() and status_label.winfo_exists():
        update_status_label("Socket.IO Connected. Checking WhatsApp...", "blue")
        check_whatsapp_status() # Check WhatsApp status once socket is up

@sio.event
def connect_error(data):
    global sio_connected
    sio_connected = False
    print(f"Socket.IO connection failed: {data}")
    if 'status_label' in globals() and status_label.winfo_exists():
        update_status_label(f"Socket.IO Connection Error. Retrying...", "red")

@sio.event
def disconnect():
    global sio_connected
    sio_connected = False
    print('Socket.IO disconnected.')
    if 'status_label' in globals() and status_label.winfo_exists():
        update_status_label("Socket.IO Disconnected. Retrying connection...", "orange")
    if 'qr_display_label' in globals() and qr_display_label.winfo_exists():
        qr_display_label.config(image='', text="QR Code (Disconnected)")
    # Do not clear chat/poll list on temporary socket disconnect if WA might still be connected

@sio.event
def qr_code(qr_data_from_socket): # Renamed to avoid conflict with qrcode module
    print(f"Received QR Code via Socket.IO.")
    if 'qr_display_label' in globals() and qr_display_label.winfo_exists():
        display_qr_code(qr_data_from_socket) # Use the received data
        update_status_label("QR Code Received. Please scan.", "#DBA800") # Dark yellow
        if 'notebook' in globals() and 'connection_tab' in globals():
            notebook.select(connection_tab)

@sio.event
def client_status(status): # Server emits 'client_status'
    global whatsapp_client_actually_ready # Global විදියට declare කරන්න
    print(f"WhatsApp Client Status from Socket.IO: {status}")
    if 'status_label' in globals() and status_label.winfo_exists():
        if status == 'ready':
            whatsapp_client_actually_ready = True # Flag එක True කරන්න
            update_status_label("WhatsApp Client is READY!", "green")
            if 'qr_display_label' in globals() and qr_display_label.winfo_exists():
                qr_display_label.config(image='', text="WhatsApp Client READY!")
            fetch_chats()
            fetch_all_poll_data_from_server()
        elif status == 'qr_pending':
            whatsapp_client_actually_ready = False # Flag එක False කරන්න
            update_status_label("Waiting for QR scan (check Connection Tab)...", "orange")
        elif status == 'logged_out':
            whatsapp_client_actually_ready = False # Flag එක False කරන්න
            update_status_label(f"WhatsApp: Logged Out. Delete 'baileys_auth_info' & restart Node server to connect new.", "red")
            clear_session_gui_elements()
        elif status in ['disconnected', 'auth_failure']:
            whatsapp_client_actually_ready = False # Flag එක False කරන්න
            update_status_label(f"WhatsApp: {status}. Please connect/reconnect.", "red")
            # clear_session_gui_elements() # තාවකාලිකව disconnect වෙනකොට clear කරන එක ගැන සැලකිලිමත් වෙන්න

def clear_session_gui_elements():
    global active_polls_data_from_server, whatsapp_client_actually_ready # Flag එක මෙතනටත් add කරන්න
    whatsapp_client_actually_ready = False # Logout/clear වලදී False කරන්න
    # global active_polls_data_from_server # Removed redundant global declaration
    active_polls_data_from_server = {}
    if 'qr_display_label' in globals() and qr_display_label.winfo_exists(): qr_display_label.config(image='', text="QR Code (Logged Out)")
    if 'poll_chat_listbox' in globals() and poll_chat_listbox.winfo_exists(): poll_chat_listbox.delete(0, tk.END)
    if 'poll_results_listbox' in globals() and poll_results_listbox.winfo_exists(): poll_results_listbox.delete(0, tk.END)
    if 'poll_results_label' in globals() and poll_results_label.winfo_exists():
        poll_results_label.config(state=tk.NORMAL)
        poll_results_label.delete('1.0', tk.END)
        poll_results_label.insert('1.0', "Logged out. Select a poll after reconnecting.")
        poll_results_label.config(state=tk.DISABLED)


@sio.event
def whatsapp_user(user_data): # If server sends user info
    if user_data and user_data.get('id'):
        print(f"Connected as: {user_data.get('name') or user_data.get('id')}")
        # Optionally display this info in the GUI

@sio.event
def poll_update_to_gui(data):
    global active_polls_data_from_server
    print(f"GUI received poll_update_to_gui: {data}")
    poll_msg_id = data.get('pollMsgId')

    if poll_msg_id:
        # Update or add the poll data
        if poll_msg_id not in active_polls_data_from_server: # If it's a new poll not initiated by this GUI
             active_polls_data_from_server[poll_msg_id] = {
                'question': data.get('question', 'Unknown Question'),
                'options': data.get('options', []),
                'results': data.get('results', {}),
                'voters': data.get('voters', {}),
                'timestamp': data.get('timestamp', time.time()*1000), # Fallback timestamp
                'selectableCount': data.get('selectableCount', 1)
            }
             populate_poll_results_listbox() # New poll, refresh the list
        else: # Existing poll, just update results and voters
            active_polls_data_from_server[poll_msg_id]['results'] = data.get('results', {})
            active_polls_data_from_server[poll_msg_id]['voters'] = data.get('voters', {})


        # If this poll is currently selected in the results tab, refresh its display
        if 'poll_results_listbox' in globals() and poll_results_listbox.winfo_exists():
            try:
                selected_indices = poll_results_listbox.curselection()
                if selected_indices:
                    selected_poll_display_text = poll_results_listbox.get(selected_indices[0])
                    # Extract msg_id from "Question (ID: ...msg_id_suffix)"
                    if f"(ID: ...{poll_msg_id[-6:]})" in selected_poll_display_text:
                        display_selected_poll_results() # Refresh display
            except Exception as e:
                print(f"Error updating selected poll display from poll_update_to_gui: {e}")
        update_status_label(f"Poll '{active_polls_data_from_server.get(poll_msg_id, {}).get('question', poll_msg_id)}' updated!", "cyan")

@sio.event
def new_poll_sent(data): # Server sends { pollMsgId: 'xyz', pollData: {...} }
    global active_polls_data_from_server
    print(f"GUI received new_poll_sent: {data}")
    poll_msg_id = data.get('pollMsgId')
    poll_data_obj = data.get('pollData')
    if poll_msg_id and poll_data_obj:
        active_polls_data_from_server[poll_msg_id] = poll_data_obj
        populate_poll_results_listbox() # Refresh the listbox with the new poll
        update_status_label(f"New poll '{poll_data_obj.get('question', 'N/A')}' added to results tab.", "magenta")
    else:
        # Fallback if data structure is different, refetch all
        fetch_all_poll_data_from_server()


@sio.event
def initial_poll_data(data): # When GUI connects, server sends all current poll data
    global active_polls_data_from_server
    print("GUI received initial_poll_data")
    active_polls_data_from_server = data if isinstance(data, dict) else {} # Ensure it's a dict
    populate_poll_results_listbox()
    # --- නිවැරදි කළ පේළිය ---
    update_status_label(f"Loaded {len(active_polls_data_from_server)} existing polls.", "blue") # "info" වෙනුවට "blue"

# --- GUI Functions ---
def update_status_label(message, color_name="blue"): # Standardized color_name
    if 'status_label' in globals() and status_label.winfo_exists():
        try:
            status_label.config(text=f"Status: {message}", fg=color_name)
            if 'root' in globals() and root.winfo_exists(): root.update_idletasks()
        except tk.TclError as e:
            print(f"Error setting color '{color_name}': {e}. Using default.")
            status_label.config(text=f"Status: {message}", fg="black")


def check_whatsapp_status():
    if 'status_label' not in globals() or not status_label.winfo_exists(): return
    update_status_label("Checking WhatsApp status via HTTP...", "blue")
    try:
        response = requests.get(NODE_API_STATUS, timeout=3) # Shorter timeout
        response.raise_for_status()
        data = response.json()
        api_status = data.get('status')
        api_qr = data.get('qrCode')
        # This HTTP check is a fallback; primary updates should come via Socket.IO client_status event
        if api_status == 'ready':
            # client_status('ready') # Let socket event handle this primarily
            if not sio_connected: update_status_label("HTTP: WA Ready (Socket disconnected)", "orange")
            else: update_status_label("HTTP: WA Ready (Socket connected)", "green")
        elif api_status == 'qr_pending' and api_qr:
            # client_status('qr_pending') # Let socket event handle this
            # display_qr_code(api_qr)
             if not sio_connected: update_status_label("HTTP: WA QR Pending (Socket disconnected)", "orange")

        elif api_status == 'disconnected':
            # client_status('disconnected')
            if not sio_connected: update_status_label("HTTP: WA Disconnected (Socket disconnected)", "red")

    except requests.exceptions.RequestException as e:
        update_status_label(f"Node server check failed: {type(e).__name__}", "red")
        print(f"HTTP status check failed: {e}")


def display_qr_code(qr_data_str):
    if 'qr_display_label' not in globals() or not qr_display_label.winfo_exists(): return
    try:
        # qrcode library is already imported at the top
        img = qrcode.make(qr_data_str)
        # Ensure it's a PIL Image object for resize
        if not hasattr(img, 'resize'): # If qrcode.make returns something else
            qr_code_obj = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
            qr_code_obj.add_data(qr_data_str)
            qr_code_obj.make(fit=True)
            img = qr_code_obj.make_image(fill_color="black", back_color="white").convert('RGB')

        img_resized = img.resize((250, 250), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img_resized)
        qr_display_label.config(image=photo, text="")
        qr_display_label.image = photo # Keep a reference!
    except Exception as e:
        update_status_label(f"Error displaying QR: {e}", "red")
        qr_display_label.config(image='', text=f"QR Display Error: {e}")
        print(f"QR display error: {e}")


def fetch_chats():
    global chat_mapping
    if 'status_label' not in globals() or not status_label.winfo_exists(): return
    if not client_is_ready(): # Helper function to check actual WA readiness
        update_status_label("WhatsApp not ready. Cannot fetch chats.", "orange")
        return

    update_status_label("Fetching chats...", "blue")
    try:
        response = requests.get(NODE_API_GET_CHATS, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('success'):
            listboxes_to_update = []
            if 'poll_chat_listbox' in globals() and poll_chat_listbox.winfo_exists():
                listboxes_to_update.append(poll_chat_listbox)

            for lb in listboxes_to_update: lb.delete(0, tk.END)
            chat_mapping.clear()
            fetched_chats_count = 0
            if 'chats' in data and data['chats'] is not None:
                for chat in data['chats']:
                    display_name = f"{chat.get('name', 'Unknown Name')} ({'Group' if chat.get('isGroup') else 'Contact'})"
                    chat_id_val = chat.get('id')
                    if chat_id_val: # Ensure chat_id is not None or empty
                        chat_mapping[display_name] = chat_id_val
                        for lb in listboxes_to_update: lb.insert(tk.END, display_name)
                        fetched_chats_count +=1
            update_status_label(f"Fetched {fetched_chats_count} chats.", "green")
        else:
            update_status_label(f"Failed to fetch chats: {data.get('message', 'No message')}", "red")
    except requests.exceptions.RequestException as e:
        update_status_label(f"Error fetching chats (HTTP): {e}", "red")
        print(f"Fetch chats error: {e}")
    except Exception as e: # Catch other potential errors
        update_status_label(f"Unexpected error fetching chats: {e}", "red")
        print(f"Unexpected fetch chats error: {e}")

def client_is_ready(): # Helper
    global whatsapp_client_actually_ready
    # print(f"Debug: client_is_ready() called. Flag is: {whatsapp_client_actually_ready}") # Debugging සඳහා
    return whatsapp_client_actually_ready

# --- Poll Sender Functions ---
def send_poll_message():
    if 'poll_question_entry' not in globals(): return
    if not client_is_ready():
        messagebox.showerror("Error", "WhatsApp client is not ready to send polls.")
        return

    question = poll_question_entry.get().strip()
    options = [opt.strip() for opt in poll_options_listbox.get(0, tk.END) if opt.strip()] # Ensure no empty options
    selected_indices = poll_chat_listbox.curselection()
    allow_multiple = allow_multiple_answers_var.get()

    if not question: messagebox.showerror("Error", "Poll question cannot be empty."); return
    if not options or len(options) < 1: messagebox.showerror("Error", "Poll must have at least one option."); return
    if len(options) > 12: messagebox.showerror("Error", "Maximum of 12 poll options allowed by WhatsApp."); return
    if not selected_indices: messagebox.showerror("Error", "Please select at least one chat/group to send the poll to."); return

    selected_chat_display_names = [poll_chat_listbox.get(i) for i in selected_indices]
    selected_chat_ids = [chat_mapping[name] for name in selected_chat_display_names if name in chat_mapping]

    if not selected_chat_ids: messagebox.showerror("Error", "No valid chats selected (ID mapping failed). Please refresh chats."); return
    if not messagebox.askyesno("Confirm Poll Submission", f"Are you sure you want to send this poll to {len(selected_chat_ids)} selected chat(s)?"): return

    update_status_label(f"Initiating poll send to {len(selected_chat_ids)} chat(s)...", "blue")
    # Non-blocking send using a thread
    threading.Thread(target=_send_polls_threaded, args=(selected_chat_ids, question, options, allow_multiple), daemon=True).start()

def _send_polls_threaded(chat_ids, question, options, allow_multiple_bool):
    success_count = 0
    fail_count = 0
    for i, chat_id in enumerate(chat_ids):
        current_status_msg = f"Sending poll ({i+1}/{len(chat_ids)}) to {chat_id}..."
        root.after(0, update_status_label, current_status_msg, "cyan") # Update GUI from thread
        try:
            payload = {
                "chatId": chat_id,
                "question": question,
                "options": options,
                "allowMultipleAnswers": allow_multiple_bool
            }
            response = requests.post(NODE_API_SEND_POLL, json=payload, timeout=15) # Increased timeout slightly
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            result = response.json()

            if result.get('success'):
                success_count += 1
                final_msg_for_chat = f"Poll sent to {chat_id} (ID: {result.get('pollMsgId', 'N/A')})"
                root.after(0, update_status_label, final_msg_for_chat, "green")
            else:
                fail_count += 1
                final_msg_for_chat = f"Failed poll to {chat_id}: {result.get('message', 'Unknown error')}"
                root.after(0, update_status_label, final_msg_for_chat, "red")
            # Anti-ban delay
            delay_s = random.uniform(anti_ban_delay_min.get(), anti_ban_delay_max.get())
            time.sleep(delay_s)
        except requests.exceptions.HTTPError as httperr:
            fail_count +=1
            err_msg = f"HTTP Error poll to {chat_id}: {httperr.response.status_code} - {httperr.response.text}"
            root.after(0, update_status_label, err_msg, "red")
            print(err_msg)
        except requests.exceptions.RequestException as reqerr: # Timeout, ConnectionError etc.
            fail_count += 1
            err_msg = f"Request Error poll to {chat_id}: {reqerr}"
            root.after(0, update_status_label, err_msg, "red")
            print(err_msg)
        except Exception as e: # Other unexpected errors
            fail_count +=1
            err_msg = f"Unexpected Error poll to {chat_id}: {e}"
            root.after(0, update_status_label, err_msg, "red")
            print(err_msg)

    final_summary = f"Poll sending finished. Success: {success_count}, Failed: {fail_count}."
    root.after(0, update_status_label, final_summary, "blue" if fail_count == 0 else "orange")


def add_poll_option():
    option = poll_option_entry.get().strip()
    if option:
        current_options = poll_options_listbox.get(0, tk.END)
        if option in current_options:
            messagebox.showwarning("Duplicate Option", "This option already exists in the list.")
            return
        if len(current_options) >= 12:
            messagebox.showwarning("Option Limit", "WhatsApp allows a maximum of 12 options per poll.")
            return
        poll_options_listbox.insert(tk.END, option)
        poll_option_entry.delete(0, tk.END)
    else:
        messagebox.showinfo("Add Option", "Please enter a non-empty option text.")

def edit_poll_option():
    selected_indices = poll_options_listbox.curselection()
    if not selected_indices:
        messagebox.showinfo("Edit Option", "Please select an option from the list to edit.")
        return
    idx = selected_indices[0]
    current_val = poll_options_listbox.get(idx)
    new_val = simpledialog.askstring("Edit Option", "Enter new text for the option:", initialvalue=current_val, parent=root)
    if new_val is not None: # User provided input (could be empty string)
        new_val_stripped = new_val.strip()
        if not new_val_stripped:
            messagebox.showwarning("Edit Option", "Option text cannot be empty.")
            return
        if new_val_stripped != current_val and new_val_stripped in poll_options_listbox.get(0, tk.END):
            messagebox.showwarning("Edit Option", "This option text already exists in the list.")
            return
        poll_options_listbox.delete(idx)
        poll_options_listbox.insert(idx, new_val_stripped)

def delete_poll_option():
    selected_indices = poll_options_listbox.curselection()
    if selected_indices:
        poll_options_listbox.delete(selected_indices[0])
    else:
        messagebox.showinfo("Delete Option", "Please select an option from the list to delete.")

def clear_poll_options():
    poll_options_listbox.delete(0, tk.END)

# --- Poll Template Management ---
def load_poll_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            messagebox.showerror("Template Error", f"Error decoding {TEMPLATES_FILE}. It might be corrupted.")
            return {}
        except Exception as e:
            messagebox.showerror("Template Error", f"Error loading templates: {e}")
            return {}
    return {}

def save_poll_templates(data):
    try:
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        messagebox.showerror("Template Error", f"Error saving templates: {e}")

def update_poll_template_dropdown():
    if 'poll_template_combobox' not in globals() or not poll_template_combobox.winfo_exists(): return
    templates = load_poll_templates()
    names = list(templates.keys())
    poll_template_combobox['values'] = names
    if names:
        poll_template_combobox.current(0) # Select first item
    else:
        poll_template_combobox.set("") # Clear if no templates

def save_current_poll_as_template():
    question_text = poll_question_entry.get().strip()
    options_list = list(poll_options_listbox.get(0, tk.END))
    if not question_text and not options_list: # Allow saving even if only one is present
        messagebox.showinfo("Save Template", "Please enter a poll question and/or options to save as a template.")
        return

    template_name = simpledialog.askstring("Save Poll Template", "Enter a name for this template:", parent=root)
    if template_name and template_name.strip():
        templates = load_poll_templates()
        templates[template_name.strip()] = {
            "question": question_text,
            "options": "\n".join(options_list) # Store options as newline separated string
        }
        save_poll_templates(templates)
        update_poll_template_dropdown()
        messagebox.showinfo("Save Template", f"Poll template '{template_name.strip()}' saved successfully!")
    elif template_name is not None: # User entered empty string
        messagebox.showwarning("Save Template", "Template name cannot be empty.")


def load_selected_poll_template(event=None): # event is passed by combobox selection
    selected_name = poll_template_combobox.get()
    templates = load_poll_templates()
    if selected_name in templates:
        template_data = templates[selected_name]
        poll_question_entry.delete(0, tk.END)
        poll_question_entry.insert(0, template_data.get("question", ""))

        clear_poll_options()
        options_str = template_data.get("options", "")
        if isinstance(options_str, str): # Ensure it's a string
            for opt in options_str.split('\n'):
                if opt.strip(): # Add only non-empty options
                    poll_options_listbox.insert(tk.END, opt.strip())
        update_status_label(f"Poll template '{selected_name}' loaded.", "blue")


def delete_selected_poll_template():
    selected_name = poll_template_combobox.get()
    if not selected_name:
        messagebox.showinfo("Delete Template", "Please select a template from the dropdown to delete.")
        return

    if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete the template '{selected_name}'?", parent=root):
        templates = load_poll_templates()
        if selected_name in templates:
            del templates[selected_name]
            save_poll_templates(templates)
            update_poll_template_dropdown() # Refresh dropdown
            poll_template_combobox.set('') # Clear selection
            # Clear current poll fields if the deleted template was loaded
            poll_question_entry.delete(0, tk.END)
            clear_poll_options()
            messagebox.showinfo("Delete Template", f"Poll template '{selected_name}' deleted successfully.")
        else:
            messagebox.showerror("Delete Template", "Selected template not found (it may have been already deleted).")

# --- Poll Results Functions ---
def fetch_all_poll_data_from_server():
    global active_polls_data_from_server
    # No need to check sio_connected here, as HTTP GET might work even if socket is temp down
    update_status_label("Fetching all poll data via HTTP...", "blue")
    try:
        response = requests.get(NODE_API_GET_ALL_POLL_DATA, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('success'):
            active_polls_data_from_server = data.get('polls', {}) # Expects a dict
            if not isinstance(active_polls_data_from_server, dict): # Basic type check
                print("Warning: Poll data from server is not a dictionary. Resetting.")
                active_polls_data_from_server = {}
            populate_poll_results_listbox()
            update_status_label(f"Fetched/Refreshed {len(active_polls_data_from_server)} polls.", "green")
        else:
            update_status_label(f"Failed to fetch poll data: {data.get('message', 'No error message')}", "red")
    except requests.exceptions.RequestException as e:
        update_status_label(f"Error fetching poll data (HTTP): {e}", "red")
        print(f"Error fetching poll data: {e}")
    except json.JSONDecodeError as je:
        update_status_label(f"Error decoding poll data JSON: {je}", "red")
        print(f"JSON Decode Error for poll data: {je}")


def populate_poll_results_listbox():
    if 'poll_results_listbox' not in globals() or not poll_results_listbox.winfo_exists(): return
    poll_results_listbox.delete(0, tk.END) # Clear existing items

    if not active_polls_data_from_server:
        poll_results_listbox.insert(tk.END, "No active polls found or fetched yet.")
        return

    # Sort polls by timestamp (newest first)
    # Ensure timestamp exists and is a number for sorting
    sorted_poll_items = sorted(
        active_polls_data_from_server.items(),
        key=lambda item: item[1].get('timestamp', 0) if isinstance(item[1].get('timestamp'), (int, float)) else 0,
        reverse=True
    )

    for poll_msg_id, poll_info in sorted_poll_items:
        question = poll_info.get('question', 'Unnamed Poll')
        # Use last 6 chars of ID for display, more readable
        display_text = f"{question[:50]}{'...' if len(question) > 50 else ''} (ID: ...{poll_msg_id[-6:]})"
        poll_results_listbox.insert(tk.END, display_text)


def display_selected_poll_results(event=None): # Bound to listbox selection
    if 'poll_results_listbox' not in globals() or not poll_results_listbox.winfo_exists(): return
    if 'poll_results_label' not in globals() or not poll_results_label.winfo_exists(): return

    selected_indices = poll_results_listbox.curselection()

    poll_results_label.config(state=tk.NORMAL) # Enable editing
    poll_results_label.delete('1.0', tk.END)   # Clear previous content

    if not selected_indices:
        poll_results_label.insert('1.0', "Select a poll from the list above to see its results.")
        poll_results_label.config(state=tk.DISABLED)
        return

    selected_item_display_text = poll_results_listbox.get(selected_indices[0])
    actual_poll_msg_id = None

    # Robustly find the poll_msg_id based on the display text suffix
    try:
        if "(ID: ..." in selected_item_display_text and selected_item_display_text.endswith(")"):
            id_suffix_with_ellipsis = selected_item_display_text.split('(ID: ...')[-1]
            id_suffix = id_suffix_with_ellipsis[:-1] # Remove trailing ')'
            for pid_key in active_polls_data_from_server.keys():
                if pid_key.endswith(id_suffix):
                    actual_poll_msg_id = pid_key
                    break
        if not actual_poll_msg_id:
            raise ValueError("Could not match listbox item to a poll ID.")
    except Exception as e:
        print(f"Error parsing poll ID from listbox item '{selected_item_display_text}': {e}")
        poll_results_label.insert('1.0', f"Error finding poll data for: {selected_item_display_text}")
        poll_results_label.config(state=tk.DISABLED)
        return

    poll_info = active_polls_data_from_server.get(actual_poll_msg_id)
    if not poll_info:
        poll_results_label.insert('1.0', f"Poll data not found for ID: {actual_poll_msg_id}")
        poll_results_label.config(state=tk.DISABLED)
        return

    # Build the results string
    results_str = f"Poll Question: {poll_info.get('question', 'N/A')}\n"
    results_str += f"Message ID: {actual_poll_msg_id}\n"
    ts = poll_info.get('timestamp')
    results_str += f"Sent Timestamp: {ts} ({time.ctime(ts/1000) if isinstance(ts, (int, float)) and ts > 0 else 'N/A'})\n"
    selectable_count = poll_info.get('selectableCount', 1) # Default to 1 if not present
    results_str += f"Allows Multiple Answers: {'Yes (Any number)' if selectable_count == 0 else f'No (Single Choice, selectable: {selectable_count})'}\n"
    results_str += "------------------------------------\nResults:\n"

    poll_option_results_map = poll_info.get('results', {}) # Keyed by option TEXT
    original_options_list = poll_info.get('options', []) # List of option TEXTS

    total_votes_on_options = sum(poll_option_results_map.values())

    # Display results based on the original option order
    for opt_text in original_options_list:
        votes_for_option = poll_option_results_map.get(opt_text, 0)
        percentage = (votes_for_option / total_votes_on_options * 100) if total_votes_on_options > 0 else 0
        results_str += f"  - \"{opt_text}\": {votes_for_option} votes ({percentage:.1f}%)\n"

    results_str += "------------------------------------\n"
    voters_data = poll_info.get('voters', {}) # Keyed by voterJid, value is array of selected hashes
    unique_voter_jids = list(voters_data.keys())
    results_str += f"Total Unique Voters Participated: {len(unique_voter_jids)}\n"
    # total_individual_selections = sum(len(v_hashes) for v_hashes in voters_data.values()) # Sum of all selected hashes by all voters
    # results_str += f"Total Individual Option Selections Made: {total_individual_selections}\n"
    results_str += f"(Note: Total votes on options ({total_votes_on_options}) might differ from unique voters if multiple selections are allowed or votes changed.)\n"

    # Optionally display who voted for what (can be very long)
    # if unique_voter_jids:
    #     results_str += "\nVoter Breakdown (JID -> Voted Option Text(s)):\n"
    #     option_hashes_to_text = poll_info.get('optionHashes', {}) # hash -> text
    #     for voter_jid, selected_hashes_arr in voters_data.items():
    #         voted_texts = [option_hashes_to_text.get(h, f"UnknownHash:{h[:6]}") for h in selected_hashes_arr]
    #         results_str += f"  - {voter_jid}: {', '.join(voted_texts)}\n"


    poll_results_label.insert('1.0', results_str)
    poll_results_label.config(state=tk.DISABLED) # Make read-only


# --- Logout Function ---
def logout_and_reconnect():
    if messagebox.askyesno("Logout & Connect New Account",
                           "This will log out the current WhatsApp account from the server "
                           "and clear the local 'baileys_auth_info' session folder on the server. "
                           "You will need to restart the Node.js server script manually "
                           "if you want it to pick up a new QR scan for a new account after this. "
                           "Continue?", parent=root):
        update_status_label("Attempting logout...", "orange")
        threading.Thread(target=_logout_threaded, daemon=True).start()

def _logout_threaded():
    global active_polls_data_from_server, whatsapp_client_actually_ready # Flag එක මෙතනටත් add කරන්න

    # Logout උත්සාහය පටන් ගන්නකොටම Client එක not ready විදියට සලකන්න
    root.after(0, lambda: globals().update(whatsapp_client_actually_ready=False))
    # GUI update එක main thread එකෙන් කරන්න root.after භාවිතා කරනවා

    try:
        response = requests.post(NODE_API_LOGOUT, timeout=15) # Slightly longer timeout for logout
        response.raise_for_status()
        result = response.json()
        if result.get('success'):
            # Don't show messagebox from thread, update GUI via root.after or status_label
            root.after(0, update_status_label, result.get('message', "Logout successful. Restart Node server for new QR."), "blue")
            root.after(0, clear_session_gui_elements) # Clear GUI elements related to session
        else:
            err_msg = result.get('message', "Failed to logout from server.")
            root.after(0, update_status_label, f"Logout Error: {err_msg}", "red")
            root.after(0, messagebox.showerror, "Logout Error", err_msg, parent=root)

    except requests.exceptions.RequestException as e:
        err_msg = f"Logout request error: {e}"
        root.after(0, update_status_label, err_msg, "red")
        root.after(0, messagebox.showerror, "Logout Error", err_msg, parent=root)
        print(err_msg)
    except Exception as e: # Catch any other unexpected error
        err_msg = f"Unexpected error during logout: {e}"
        root.after(0, update_status_label, err_msg, "red")
        root.after(0, messagebox.showerror, "Logout Error", err_msg, parent=root)
        print(err_msg)


# --- GUI Setup ---
root = tk.Tk()
root.title(f"WhatsApp Poll Master Deluxe - v{APP_VERSION}") # Include version in title
root.geometry("950x800") # Slightly larger

status_label = ttk.Label(root, text="Status: Initializing GUI...", relief=tk.SUNKEN, anchor=tk.W, font=status_font, style="TLabel") # Use ttk.Label
status_label.pack(side=tk.BOTTOM, fill=tk.X, ipady=3)

main_frame = ttk.Frame(root, padding=10) # Use ttk.Frame and padding
main_frame.pack(fill=tk.BOTH, expand=True)

# Define base font styles first, as they are used by status_label before style object is fully configured
base_font_family = "Segoe UI"
base_font_size = 10
bold_font_size = 10

base_font = (base_font_family, base_font_size)
bold_font = (base_font_family, bold_font_size, "bold")
status_font = (base_font_family, base_font_size) # Can be same or different
label_font = (base_font_family, base_font_size)
button_font = (base_font_family, 9) # Slightly smaller for some buttons
entry_font = (base_font_family, base_font_size)
listbox_font = (base_font_family, 9)
tab_font = (base_font_family, bold_font_size, "bold")
labelframe_label_font = (base_font_family, bold_font_size, "bold")
main_title_font = (base_font_family, 14, "bold")
small_bold_font = (base_font_family, 9, "bold")

# Styling for ttk widgets
style = ttk.Style()
try:
    style.theme_use('clam')
except tk.TclError:
    print("Clam theme not available, using default.") # Fallback for environments where clam is not present

# Configure styles
style.configure("TNotebook", tabposition='n') # Tabs on top
style.configure("TNotebook.Tab", font=tab_font, padding=[12, 6]) # Increased padding
style.configure("TLabelFrame", font=label_font, padding=10) # Padding for the frame content
style.configure("TLabelFrame.Label", font=labelframe_label_font, padding=(0, 0, 0, 5)) # Padding around the label text (L,T,R,B)

style.configure("TButton", font=button_font, padding=6)
style.configure("Bold.TButton", font=bold_font, padding=6) # For more prominent buttons
style.configure("Refresh.TButton", font=button_font, padding=6) # Specific style if needed
style.configure("Small.TButton", font=(base_font_family, 8), padding=4)


style.configure("TLabel", font=label_font, padding=3)
style.configure("Bold.TLabel", font=bold_font, padding=3)

style.configure("TEntry", font=entry_font, padding=4)
style.configure("TCombobox", font=entry_font, padding=4) # Match TEntry
style.map("TCombobox", fieldbackground=[('readonly','white')]) # Ensure readonly combobox looks good
style.configure("TCheckbutton", font=label_font)

# Custom style for the main title label in Connection Tab
style.configure("MainTitle.TLabel", font=main_title_font)


notebook = ttk.Notebook(main_frame) # Style will be applied via TNotebook configuration
notebook.pack(fill=tk.BOTH, expand=True)

# == Connection Tab ==
connection_tab = ttk.Frame(notebook, padding=10)
notebook.add(connection_tab, text="📶 Connection")
connection_tab.columnconfigure(0, weight=1)
connection_tab.rowconfigure(1, weight=1) # QR Label should expand

ttk.Label(connection_tab, text="WhatsApp Web Connection", style="MainTitle.TLabel").grid(row=0, column=0, pady=(5,15), sticky="ew") # Increased pady
qr_display_label = tk.Label(connection_tab, text="QR Code Area (Connecting...)", bg="white", relief=tk.SOLID, borderwidth=1, height=15, width=40, font=(base_font_family, 8)) # Adjusted font, bg, relief, borderwidth
qr_display_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10)) # Increased padx & pady

connection_button_frame = ttk.Frame(connection_tab) # Use ttk.Frame
connection_button_frame.grid(row=2, column=0, pady=(15,10)) # Increased pady
#ttk.Button(connection_button_frame, text="🔄 Check Status / Connect", command=check_whatsapp_status, style="Bold.TButton").pack(side=tk.LEFT, padx=5) # Keep style if it's distinct
ttk.Button(connection_button_frame, text="🔄 Refresh Chats", command=fetch_chats, style="Bold.TButton").pack(side=tk.LEFT, padx=10) # Increased padx
ttk.Button(connection_button_frame, text="🚪 Logout & Clear Session", command=logout_and_reconnect, style="Bold.TButton").pack(side=tk.LEFT, padx=10) # Increased padx


# == Poll Sender Tab ==
poll_sender_tab = ttk.Frame(notebook, padding=10)
notebook.add(poll_sender_tab, text="📊 Poll Sender")

# Poll Templates section
poll_template_frame = ttk.LabelFrame(poll_sender_tab, text="Poll Templates", padding=10)
poll_template_frame.pack(fill=tk.X, padx=5, pady=(10,10))
poll_template_frame.columnconfigure(0, weight=1) # Allow combobox to expand
poll_template_frame.columnconfigure(1, weight=0) # Buttons take their own space

poll_template_combobox = ttk.Combobox(poll_template_frame, state="readonly", width=40, font=entry_font)
poll_template_combobox.grid(row=0, column=0, padx=(0,10), pady=5, sticky=tk.EW)
poll_template_combobox.bind("<<ComboboxSelected>>", load_selected_poll_template)

ptb_frame = ttk.Frame(poll_template_frame)
ptb_frame.grid(row=0, column=1, padx=10, pady=5)
ttk.Button(ptb_frame, text="💾 Save Current", command=save_current_poll_as_template, style="Small.TButton").pack(side=tk.LEFT, padx=3)
ttk.Button(ptb_frame, text="🗑️ Delete Selected", command=delete_selected_poll_template, style="Small.TButton").pack(side=tk.LEFT, padx=3)


# Chat/Group Selection
ttk.Label(poll_sender_tab, text="Select Chats/Groups for Poll:", font=small_bold_font).pack(pady=(10,2), anchor=tk.W, padx=5)
poll_chat_listbox_frame = ttk.Frame(poll_sender_tab)
poll_chat_listbox_frame.pack(fill=tk.X, padx=5, pady=5) # Increased pady, removed ipady
poll_chat_listbox_scrollbar = ttk.Scrollbar(poll_chat_listbox_frame, orient=tk.VERTICAL)
poll_chat_listbox = tk.Listbox(poll_chat_listbox_frame, selectmode=tk.EXTENDED, yscrollcommand=poll_chat_listbox_scrollbar.set, exportselection=False, font=listbox_font, height=6)
poll_chat_listbox_scrollbar.config(command=poll_chat_listbox.yview)
poll_chat_listbox_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
poll_chat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

# Poll Question
ttk.Label(poll_sender_tab, text="Poll Question:", anchor=tk.W, font=label_font).pack(fill=tk.X, padx=5, pady=(15,2))
poll_question_entry = ttk.Entry(poll_sender_tab, width=60, font=entry_font)
poll_question_entry.pack(fill=tk.X, padx=5, pady=(0,10)) # Increased pady, removed ipady

# Allow Multiple Answers Checkbox
allow_multiple_answers_var = tk.BooleanVar(value=False)
allow_multiple_checkbox = ttk.Checkbutton(poll_sender_tab, text="Allow multiple answers", variable=allow_multiple_answers_var)
allow_multiple_checkbox.pack(padx=5, pady=(0,10), anchor=tk.W) # Increased pady

# Poll Options Management
pom_frame = ttk.LabelFrame(poll_sender_tab, text="Poll Options (Enter one by one, max 12)", padding=10)
pom_frame.pack(fill=tk.X, padx=5, pady=10)
pom_frame.columnconfigure(0, weight=1) # Entry and listbox side expands
pom_frame.columnconfigure(1, weight=0) # Buttons side fixed

pom_left_frame = ttk.Frame(pom_frame)
pom_left_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0,10))
pom_left_frame.rowconfigure(1, weight=1) # Listbox_outer_frame expands vertically
pom_left_frame.columnconfigure(0, weight=1) # Entry and Listbox_outer_frame expand horizontally

poll_option_entry = ttk.Entry(pom_left_frame, width=40, font=entry_font)
poll_option_entry.grid(row=0, column=0, sticky=tk.EW, pady=(0,5))

poll_options_listbox_outer_frame = ttk.Frame(pom_left_frame)
poll_options_listbox_outer_frame.grid(row=1, column=0, sticky=tk.NSEW)
poll_options_listbox_outer_frame.rowconfigure(0, weight=1)
poll_options_listbox_outer_frame.columnconfigure(0, weight=1)

opt_scrollbar = ttk.Scrollbar(poll_options_listbox_outer_frame, orient=tk.VERTICAL)
opt_scrollbar.grid(row=0, column=1, sticky=tk.NS)
poll_options_listbox = tk.Listbox(poll_options_listbox_outer_frame, height=5, font=listbox_font, yscrollcommand=opt_scrollbar.set)
poll_options_listbox.grid(row=0, column=0, sticky=tk.NSEW)
opt_scrollbar.config(command=poll_options_listbox.yview)


pob_frame = ttk.Frame(pom_frame)
pob_frame.grid(row=0, column=1, sticky=tk.NS, padx=10)
btn_width = 8
ttk.Button(pob_frame, text="Add", command=add_poll_option, width=btn_width, style="Small.TButton").pack(pady=3, fill=tk.X)
ttk.Button(pob_frame, text="Edit", command=edit_poll_option, width=btn_width, style="Small.TButton").pack(pady=3, fill=tk.X)
ttk.Button(pob_frame, text="Delete", command=delete_poll_option, width=btn_width, style="Small.TButton").pack(pady=3, fill=tk.X)
ttk.Button(pob_frame, text="Clear All", command=clear_poll_options, width=btn_width, style="Small.TButton").pack(pady=3, fill=tk.X)


# Anti-Ban Settings
anti_ban_frame = ttk.LabelFrame(poll_sender_tab, text="Send Delay (seconds between messages)", padding=10)
anti_ban_frame.pack(fill=tk.X, padx=5, pady=(15,10)) # Increased pady
anti_ban_delay_min = tk.DoubleVar(value=2.0)
anti_ban_delay_max = tk.DoubleVar(value=4.0)
ttk.Label(anti_ban_frame, text="Min:", font=label_font).pack(side=tk.LEFT, padx=(0,2))
ttk.Entry(anti_ban_frame, textvariable=anti_ban_delay_min, width=5, font=entry_font).pack(side=tk.LEFT, padx=(0,10))
ttk.Label(anti_ban_frame, text="Max:", font=label_font).pack(side=tk.LEFT, padx=(0,2))
ttk.Entry(anti_ban_frame, textvariable=anti_ban_delay_max, width=5, font=entry_font).pack(side=tk.LEFT, padx=(0,10))

# Send Poll Button
send_poll_button = ttk.Button(poll_sender_tab, text="🚀 Send Poll to Selected Chats", command=send_poll_message, style="Bold.TButton")
send_poll_button.pack(pady=(15,10), ipady=8, fill=tk.X, padx=5) # Increased ipady and pady


# == Poll Results Tab ==
poll_results_tab = ttk.Frame(notebook, padding=10)
notebook.add(poll_results_tab, text="📈 Poll Results")

# Frame for listing polls and refreshing
poll_list_management_frame = ttk.Frame(poll_results_tab)
poll_list_management_frame.pack(fill=tk.X, pady=(5,10)) # Increased pady
ttk.Label(poll_list_management_frame, text="Previously Sent Polls (Newest First):", font=bold_font).pack(side=tk.LEFT, anchor=tk.W, padx=(0,10)) # Added padx
refresh_polls_button = ttk.Button(poll_list_management_frame, text="🔄 Refresh Poll List & Results", command=fetch_all_poll_data_from_server, style="Refresh.TButton")
refresh_polls_button.pack(side=tk.RIGHT, padx=5) # Added padx

# Listbox for polls
poll_results_listbox_frame = ttk.Frame(poll_results_tab)
poll_results_listbox_frame.pack(fill=tk.X, pady=10) # Increased pady
pr_scrollbar = ttk.Scrollbar(poll_results_listbox_frame, orient=tk.VERTICAL)
poll_results_listbox = tk.Listbox(poll_results_listbox_frame, yscrollcommand=pr_scrollbar.set, exportselection=False, font=listbox_font, height=10)
pr_scrollbar.config(command=poll_results_listbox.yview); pr_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
poll_results_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
poll_results_listbox.bind("<<ListboxSelect>>", display_selected_poll_results)

# Frame for displaying results of the selected poll
poll_results_display_outer_frame = ttk.LabelFrame(poll_results_tab, text="Selected Poll Details & Results", padding=10)
poll_results_display_outer_frame.pack(fill=tk.BOTH, expand=True, pady=(10,5)) # Increased pady

poll_results_label = scrolledtext.ScrolledText(
    poll_results_display_outer_frame, wrap=tk.WORD, font=(base_font_family, 9),
    state=tk.DISABLED, relief=tk.SOLID, borderwidth=1, height=15
)
poll_results_label.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
# Initial text set in display_selected_poll_results or populate_poll_results_listbox if none selected

# --- Socket.IO Connection Thread ---
def attempt_sio_connection():
    """Attempt to connect to Socket.IO server in a loop."""
    if not sio.connected:
        try:
            print("Attempting to connect to Socket.IO server...")
            sio.connect(NODE_SERVER_URL, wait_timeout=5) # Shorter wait for individual attempt
        except socketio.exceptions.ConnectionError as e:
            # This error is expected if server is down, will be handled by sio's reconnection logic
            print(f"Socket.IO connection attempt failed (will retry via client): {e}")
            if 'status_label' in globals() and status_label.winfo_exists():
                 root.after(0, update_status_label, "Socket.IO connection failed. Retrying...", "red")
        except Exception as e:
            print(f"Unexpected error during Socket.IO connection attempt: {e}")
            if 'status_label' in globals() and status_label.winfo_exists():
                 root.after(0, update_status_label, f"Socket.IO error: {e}", "red")

def sio_connection_thread_func():
    while True:
        if not sio.connected:
            attempt_sio_connection()
        time.sleep(10) # Interval between connection attempts if not connected

# --- Initializations & Main Loop ---
def initial_gui_setup():
    update_poll_template_dropdown()
    # Initial fetch of poll data from server if it's already running
    # Do this slightly after GUI is up to ensure labels exist
    root.after(1000, fetch_all_poll_data_from_server)
    # Initial check of WhatsApp status via HTTP as a fallback
    root.after(500, check_whatsapp_status)


def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit the Poll Master application?"):
        if sio.connected:
            print("Disconnecting Socket.IO client...")
            sio.disconnect()
        root.destroy()
        print("Application closed.")

if __name__ == "__main__":
    root.protocol("WM_DELETE_WINDOW", on_closing)
    # Start the Socket.IO connection manager thread
    sio_thread = threading.Thread(target=sio_connection_thread_func, daemon=True)
    sio_thread.start()

    # Schedule initial GUI setup tasks
    root.after(100, initial_gui_setup)

    root.mainloop()
