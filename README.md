# PollMasters - WhatsApp Poll Management Tool

PollMasters is a desktop application designed to help you create, send, and manage polls on WhatsApp. It features a Node.js backend that uses the Baileys library to interact with WhatsApp, and a Python Tkinter frontend for a user-friendly graphical interface.

## ⚠Note

This project is licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for the full license text.

## Disclaimer

This software is provided "as-is", without any express or implied warranty. In no event shall the authors or contributors be liable for any claim, damages, or other liability, whether in an action of contract, tort, or otherwise, arising from, out of, or in connection with the software or the use or other dealings in the software.
Use this tool responsibly and be mindful of WhatsApp's Terms of Service. Automated messaging or bulk polling can lead to account restrictions if not used carefully. The developers of this tool are not responsible for any misuse or consequences thereof!.

## Features

* **WhatsApp Connection:** Connect to your WhatsApp account by scanning a QR code.
* **Poll Creation:**
    * Define a poll question and multiple answer options (supports 1 to 12 options).
    * Specify if multiple answers are allowed for a poll.
* **Poll Sending:**
    * Fetch and select from your available WhatsApp chats and groups.
    * Send created polls to multiple selected chats/groups.
    * Adjustable delay between sending messages to help prevent account flagging.
* **Results Tracking:**
    * View real-time updates for poll results in the GUI.
    * See vote counts and percentages for each option.
    * Lists previously sent polls and their current results.
* **Template Management:**
    * Save frequently used polls as templates.
    * Load, and delete poll templates for quick reuse.
* **Session Management:** Logout from the current WhatsApp session and clear local session data.

## Tech Stack

* **Backend:**
    * Node.js
    * Express.js
    * [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys) (WhatsApp Web API)
    * Socket.IO (Real-time communication with frontend)
    * Pino (Logger)
* **Frontend:**
    * Python 3
    * Tkinter (Standard Python GUI library)
    * `requests` (HTTP requests)
    * `python-socketio` (Socket.IO client)
    * `Pillow` (Image processing for QR codes)
    * `qrcode` (Generating QR codes)

## Prerequisites

* Node.js (Version >= 20.0.0 recommended, as required by Baileys).
* Python 3 (Tkinter is usually included with standard Python installations).
* `pip` for installing Python packages.

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd PollMasters-90385d64a5a90c82e73013062db55ec42c6cdff9 
    ```
    (Replace `<your-repository-url>` with the actual URL of your repository after you upload it).

2.  **Backend Setup (Node.js):**
    Navigate to the backend directory and install dependencies:
    ```bash
    cd backend_node
    npm install
    cd .. 
    ```

3.  **Frontend Setup (Python):**
    Install the required Python packages using pip. It's recommended to do this in a Python virtual environment:
    ```bash
    # Example for creating and activating a virtual environment (optional but recommended)
    # python -m venv venv
    # source venv/bin/activate  # On Windows: venv\Scripts\activate

    pip install requests python-socketio Pillow qrcode
    ```

## Running the Application

1.  **Start the Backend Server:**
    Open a terminal, navigate to the `backend_node` directory, and run:
    ```bash
    cd backend_node
    node server.js
    ```
    The server will start. If you're not logged in to WhatsApp, it should print a QR code in the terminal (and also send it to the GUI once the GUI connects).

2.  **Run the Frontend GUI:**
    Open another terminal, navigate to the `frontend_python` directory (or the root `PollMasters-90385d64a5a90c82e73013062db55ec42c6cdff9` directory if `app.py` is run from there and `poll_templates.json` is also at the root), and run:
    ```bash
    # If app.py is inside frontend_python and poll_templates.json is at project root:
    # You might need to run app.py from the project root or adjust TEMPLATES_FILE path in app.py
    # Assuming you run from frontend_python and templates file is one level up:
    cd frontend_python 
    python app.py 
    ```
    The GUI application window should appear.

## Usage

1.  **Connect to WhatsApp:**
    * Once both backend and frontend are running, the frontend GUI will attempt to connect to the backend via Socket.IO.
    * Go to the "Connection" tab in the GUI.
    * If not logged in to WhatsApp on the backend, a QR code should be displayed in the GUI (it's also printed in the Node.js backend terminal).
    * Scan the QR code with your WhatsApp mobile app (Settings > Linked Devices > Link a device).
    * The status in the GUI should update, eventually showing "WhatsApp Client is READY!".

2.  **Sending Polls:**
    * Navigate to the "Poll Sender" tab.
    * Click "Refresh Chats" to load your WhatsApp chats and groups.
    * Select one or more chats/groups from the list.
    * Enter your poll question and add options (WhatsApp allows 1-12 options).
    * Check the "Allow multiple answers" box if you want users to select more than one option.
    * Click "Send Poll".

3.  **Viewing Results:**
    * Go to the "Poll Results" tab.
    * Polls sent during the current session (or fetched from the server if it was restarted with an active session) will be listed.
    * Click on a poll in the list to see its detailed results, including vote counts for each option and percentages.
    * Results should update in real-time as new votes are received by the backend.

4.  **Poll Templates:**
    * In the "Poll Sender" tab, you can save the current poll configuration (question and options) as a template using the "Save Current" button.
    * Use the dropdown menu to load an existing template. Templates are saved in `poll_templates.json`.

5.  **Logout:**
    * On the "Connection" tab, use the "Logout & Clear Session" button. This will log out the current WhatsApp account from the server and attempt to delete the local session files (`baileys_auth_info` directory).
