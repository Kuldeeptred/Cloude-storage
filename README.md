# Cloude-storage
# ☁️ Cloud File Storage System (Flask + MongoDB)

A **Cloud File Storage Web Application** built using **Python Flask and MongoDB**.
This project allows users to **register, login, upload files, and securely access their stored files online**.

Each file is stored on the server and linked with the **authenticated user account**, ensuring secure access control.

---

# 🚀 Features

* 🔐 User Registration and Login
* 🔑 Password Hashing for Security
* 📁 Upload Files to Cloud Storage
* 📥 Download and View Uploaded Files
* 👤 User-based File Access
* 🌐 Simple Web Interface using HTML and CSS
---

# 🛠 Technologies Used

### Backend

* Python
* Flask

### Database

* MongoDB

### Frontend

* HTML
* CSS

---

# 📂 Project Structure

```
CloudFileStorageMongo/
│
├── __pycache__/                # Python cache files
│
├── static/                     # CSS files
│   ├── auth.css
│   ├── style.css
│   └── welcode.css
│
├── templates/                  # HTML templates
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── viewer.html
│   └── welcome.html
│
├── uploads/                    # Uploaded user files
│
├── app.py                      # Main Flask application
│
└── README.md                   # Project documentation
```

---

# ⚙️ Installation

### 1️⃣ Clone Repository

```bash
git clone https://github.com/your-username/CloudFileStorageMongo.git
```

### 2️⃣ Move into Project Folder

```bash
cd CloudFileStorageMongo
```

### 3️⃣ Install Required Packages

```bash
pip install flask pymongo werkzeug
```

### 4️⃣ Run Flask Application

```bash
python app.py
```

### 5️⃣ Open in Browser

```
http://127.0.0.1:5000
```

---

# 🔐 Security Features

* Password hashing using **Werkzeug**
* Session based login system
* User authentication required for file access
* File access restricted per user

---

# 📌 Future Improvements

* File sharing using secure links
* Email verification system
* File encryption
* Deploy on cloud (AWS / Render / Railway)

---

# 👨‍💻 Author

**Kuldeep Kamejaliya**
Diploma in Computer Engineering

### Interests

* Python Development
* Machine Learning
* Web Development
* Cloud Computing

---

⭐ If you like this project, consider **starring the repository on GitHub**.
