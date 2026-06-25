# PDF to HTML Webifier Automation Service

This project automates the conversion of PDF documents into semantic, responsive, and beautiful HTML pages (Webifiers) with a custom sidebar navigation and interactive image/video slots. 

It runs a local directory watcher to automatically convert PDFs as they are added, and hosts a web interface for uploading files and viewing the results.

---

## Prerequisites

Make sure you have **Python 3.8 or higher** installed on your system.

---

## Setup & Installation

1. **Clone or download** this project folder to your local machine.
2. **Open your Terminal** and navigate to the project directory:
   ```bash
   cd /Users/nithinbodla/Downloads/PDF-to-HTML-Automation
   ```
3. **Install the required Python modules**:
   ```bash
   pip install -r requirements.txt
   ```
   *(This will install `pdfplumber`, `PyMuPDF` (fitz), `beautifulsoup4`, and `watchdog`.)*

---

## How to Run

1. Start the automation server:
   ```bash
   python app.py
   ```
2. Once started, you will see a console output indicating:
   - The web server is listening on port **8081**.
   - The `dropzone/` directory is being monitored.

---

## How to Use the Webifier

There are two ways to convert your PDFs:

### Method A: Using the Web Interface (Recommended)
1. Open your browser and go to:
   ```
   http://localhost:8081/index.html
   ```
2. Drag and drop any `.pdf` file onto the dropzone on the page.
3. The page will upload the PDF, automatically convert it, and provide a direct link to open the newly generated Webifier HTML page.

### Method B: Manual File Dropping
1. Drop any `.pdf` file directly into the `./dropzone` folder in your project directory.
2. The running Python script will detect the new file, process it, and output a corresponding `.html` file (with the same name as your PDF) directly in the project root directory.
3. Access your page via:
   ```
   http://localhost:8081/<your-pdf-filename>.html
   ```

---

## How Media Slots & Custom Images Work

- The generated HTML pages contain interactive **image/video slots** where you can click to upload or link custom media (such as YouTube videos, local images, etc.).
- When you set a media item in a slot, it is automatically saved to [media_data.json](file:///Users/nithinbodla/Downloads/PDF-to-HTML-Automation/media_data.json) on the server.
- The media settings are saved under the respective document's title (its PDF base name).
- When any generated HTML file is loaded in the browser, it loads the correct images and videos mapping specifically to its own title.

---

## Project Structure

```
PDF-to-HTML-Automation/
├── app.py              # Main Python service (Web server + Directory watcher + PDF parser)
├── index.html          # Upload landing page
├── style.css           # General styles & theme configuration
├── media_data.json     # Saved slot media configuration (autosaved)
├── dropzone/           # Folder where PDFs are uploaded/monitored
├── media/              # Folder where extracted assets are stored
└── requirements.txt    # Required Python packages list
```
### Video Reference link
- https://www.awesomescreenshot.com/video/53674023?key=5f4c12743fe223b5c5ed71a1f08aff98
