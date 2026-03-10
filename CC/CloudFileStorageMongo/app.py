from flask import Flask, render_template, request, redirect, send_from_directory, url_for, session, flash, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import mimetypes

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Per-user storage quota (1 GB)
USER_MAX_QUOTA = 1 * 1024 * 1024 * 1024

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Simple upload folder path
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Create upload folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# MongoDB connection
try:
    client = MongoClient("mongodb://localhost:27017/")
    db = client["cloud_storage"]
    collection = db["files"]
    users_collection = db["users"]
    print("MongoDB connected successfully")
except Exception as e:
    print(f"MongoDB connection error: {e}")

@app.after_request
def add_cache_headers(response):
    """Add no-cache headers to prevent browser caching"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to access that page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def format_size(num):
    """Format bytes to human readable size"""
    if num is None:
        return "—"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def get_file_category(filename):
    """Categorize file by extension"""
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    
    image_exts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp', 'ico', 'tiff']
    video_exts = ['mp4', 'avi', 'mkv', 'mov', 'flv', 'wmv', 'webm', '3gp', 'm4v']
    audio_exts = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'wma', 'opus']
    doc_exts = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf', 'odt']
    zip_exts = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2']
    
    if ext in image_exts:
        return 'Images'
    elif ext in video_exts:
        return 'Videos'
    elif ext in audio_exts:
        return 'Audio'
    elif ext in doc_exts:
        return 'Documents'
    elif ext in zip_exts:
        return 'Zip'
    else:
        return 'Others'

def get_file_path(file_doc):
    """Get the full filesystem path for a file document"""
    filename = file_doc.get('filename')
    path = file_doc.get('path', '')
    
    # Remove leading slash if present
    if path and path.startswith('/'):
        path = path[1:]
    
    # Join paths
    if path:
        return os.path.join(UPLOAD_FOLDER, path, filename)
    else:
        return os.path.join(UPLOAD_FOLDER, filename)

def get_storage_stats(user):
    """Calculate storage statistics for a user"""
    total_size = 0
    storage_by_type = {'Images': 0, 'Videos': 0, 'Audio': 0, 'Documents': 0, 'Others': 0}
    
    all_files = collection.find({"uploaded_by": user, "is_folder": False})
    for f in all_files:
        file_path = get_file_path(f)
        if os.path.exists(file_path):
            try:
                file_size = os.path.getsize(file_path)
                total_size += file_size
                category = get_file_category(f.get('filename', ''))
                storage_by_type[category] += file_size
            except OSError:
                pass
    
    return total_size, storage_by_type

def get_breadcrumbs(path):
    """Generate breadcrumb list from path"""
    breadcrumbs = [{"name": "Home", "path": ""}]
    if path and path != "/":
        parts = path.strip("/").split("/")
        current_path = ""
        for part in parts:
            current_path += "/" + part if current_path else part
            breadcrumbs.append({"name": part, "path": current_path})
    return breadcrumbs

@app.route("/")
@login_required
def index():
    user = session.get("user")
    current_path = request.args.get("path", "").strip()
    
    # Normalize path
    if current_path:
        if not current_path.startswith("/"):
            current_path = "/" + current_path
        if current_path.endswith("/") and current_path != "/":
            current_path = current_path.rstrip("/")
    
    # Get all items in current path
    items = []
    query = {"uploaded_by": user}
    
    if current_path and current_path != "/":
        query["path"] = current_path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    # Get items from database
    for item in collection.find(query).sort("is_folder", -1).sort("name", 1):
        # Convert ObjectId to string
        item["_id"] = str(item["_id"])
        
        # Set name if not present
        if "name" not in item and "filename" in item:
            item["name"] = item["filename"]
        
        # For files, check if they exist on disk
        if not item.get("is_folder", False):
            file_path = get_file_path(item)
            if not os.path.exists(file_path):
                # Remove stale database entry
                collection.delete_one({"_id": ObjectId(item["_id"])})
                continue
            
            # Get file size
            try:
                size = os.path.getsize(file_path)
                item["size"] = size
                item["size_readable"] = format_size(size)
                item["category"] = get_file_category(item["filename"])
            except OSError:
                item["size"] = 0
                item["size_readable"] = "0 B"
                item["category"] = "Others"
        
        items.append(item)
    
    # Storage statistics
    total_size, storage_by_type = get_storage_stats(user)
    max_quota = USER_MAX_QUOTA
    remaining = max(0, max_quota - total_size)
    
    storage_breakdown = {}
    for category, size in storage_by_type.items():
        storage_breakdown[category] = {
            'size': size,
            'size_readable': format_size(size),
            'percentage': round((size / total_size) * 100, 1) if total_size > 0 else 0
        }
    
    breadcrumbs = get_breadcrumbs(current_path)
    
    return render_template("index.html", 
                         items=items, 
                         user=user, 
                         current_path=current_path,
                         breadcrumbs=breadcrumbs,
                         remaining_storage=format_size(remaining), 
                         used_storage=format_size(total_size), 
                         max_storage=format_size(max_quota), 
                         storage_breakdown=storage_breakdown,
                         storage_percentage=round((total_size / max_quota) * 100, 1) if max_quota > 0 else 0)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for("register"))
        if users_collection.find_one({"username": username}):
            flash("Username already taken.", "danger")
            return redirect(url_for("register"))
        hashed = generate_password_hash(password)
        users_collection.insert_one({"username": username, "password": hashed})
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        user = users_collection.find_one({"username": username})
        if not user or not check_password_hash(user["password"], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))
        session["user"] = username
        flash(f"Welcome, {username}!", "success")
        return redirect(url_for("welcome"))
    return render_template("login.html")

@app.route("/welcome")
@login_required
def welcome():
    """Landing / Welcome page shown after login before dashboard."""
    user = session.get("user")
    return render_template("welcome.html", user=user)

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    user = session.get("user")
    file = request.files.get("file")
    path = request.form.get("path", "").strip()
    
    # Normalize path
    if path and not path.startswith("/"):
        path = "/" + path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    
    if not file or not file.filename:
        return jsonify({"success": False, "message": "No file selected.", "type": "warning"}), 400
    
    # Calculate user's storage usage
    total_size = 0
    for f in collection.find({"uploaded_by": user, "is_folder": False}):
        file_path = get_file_path(f)
        if os.path.exists(file_path):
            try:
                total_size += os.path.getsize(file_path)
            except OSError:
                pass
    
    # Check quota
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if total_size + file_size > USER_MAX_QUOTA:
        remaining_mb = max(0, (USER_MAX_QUOTA - total_size) // (1024*1024))
        return jsonify({"success": False, "message": f"Storage quota exceeded. You have {remaining_mb} MB left.", "type": "danger"}), 400
    
    # Create folder structure
    if path and path != "/":
        # Remove leading slash for filesystem path
        rel_path = path[1:] if path.startswith('/') else path
        upload_dir = os.path.join(UPLOAD_FOLDER, rel_path)
    else:
        upload_dir = UPLOAD_FOLDER
        path = ""  # Set to empty string for root
    
    os.makedirs(upload_dir, exist_ok=True)
    
    # Secure filename
    original_filename = file.filename
    safe_name = secure_filename(original_filename)
    if not safe_name:
        safe_name = f"file_{int(datetime.now().timestamp())}"
    
    # Handle duplicate filenames
    base, ext = os.path.splitext(safe_name)
    counter = 1
    final_filename = safe_name
    while os.path.exists(os.path.join(upload_dir, final_filename)):
        final_filename = f"{base}_{counter}{ext}"
        counter += 1
    
    # Save file
    file.save(os.path.join(upload_dir, final_filename))
    
    # Save to database
    file_doc = {
        "name": final_filename,
        "filename": final_filename,
        "original_filename": original_filename,
        "path": path,  # Store with leading slash format for consistency
        "is_folder": False,
        "upload_time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "uploaded_by": user
    }
    
    collection.insert_one(file_doc)
    return jsonify({"success": True, "message": "File uploaded successfully.", "type": "success"})

@app.route("/download/<path:filepath>")
@login_required
def download_file(filepath):
    """Download a file using path in URL"""
    user = session.get("user")
    
    # Split into directory and filename
    directory = os.path.dirname(filepath)
    filename = os.path.basename(filepath)
    
    # Find the file in database
    query = {
        "uploaded_by": user,
        "filename": filename,
        "is_folder": False
    }
    
    if directory and directory != '.':
        # Add leading slash for database query
        db_path = '/' + directory if not directory.startswith('/') else directory
        query["path"] = db_path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    file_doc = collection.find_one(query)
    
    if not file_doc:
        flash("File not found or access denied.", "danger")
        return redirect(url_for("index"))
    
    # Get the full filesystem path
    if directory and directory != '.':
        # Remove leading slash for filesystem
        fs_path = directory[1:] if directory.startswith('/') else directory
        full_dir = os.path.join(UPLOAD_FOLDER, fs_path)
    else:
        full_dir = UPLOAD_FOLDER
    
    full_path = os.path.join(full_dir, filename)
    
    if not os.path.exists(full_path):
        collection.delete_one({"_id": file_doc["_id"]})
        flash("File not found on disk.", "danger")
        return redirect(url_for("index"))
    
    return send_from_directory(full_dir, filename, as_attachment=True)

@app.route("/download")
@login_required
def download():
    """Download file using query parameters"""
    user = session.get("user")
    filename = request.args.get("filename", "").strip()
    path = request.args.get("path", "").strip()
    
    if not filename:
        flash("No file specified.", "danger")
        return redirect(url_for("index"))
    
    # Find the file
    query = {"uploaded_by": user, "filename": filename, "is_folder": False}
    
    if path:
        query["path"] = path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    file_doc = collection.find_one(query)
    
    if not file_doc:
        # Try with original_filename
        query = {"uploaded_by": user, "original_filename": filename, "is_folder": False}
        if path:
            query["path"] = path
        else:
            query["path"] = {"$in": ["", None, "/"]}
        file_doc = collection.find_one(query)
    
    if not file_doc:
        flash("File not found or access denied.", "danger")
        return redirect(url_for("index", path=path))
    
    # Get filesystem path
    file_path = get_file_path(file_doc)
    
    if not os.path.exists(file_path):
        collection.delete_one({"_id": file_doc["_id"]})
        flash("File not found on disk.", "danger")
        return redirect(url_for("index", path=path))
    
    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    
    return send_from_directory(directory, filename, as_attachment=True)

@app.route("/preview/<path:filepath>")
@login_required
def preview_file(filepath):
    """Preview a file using path in URL"""
    user = session.get("user")
    
    directory = os.path.dirname(filepath)
    filename = os.path.basename(filepath)
    
    # Find the file
    query = {
        "uploaded_by": user,
        "filename": filename,
        "is_folder": False
    }
    
    if directory and directory != '.':
        db_path = '/' + directory if not directory.startswith('/') else directory
        query["path"] = db_path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    file_doc = collection.find_one(query)
    
    if not file_doc:
        flash("File not found or access denied.", "danger")
        return redirect(url_for("index"))
    
    # Get filesystem path
    if directory and directory != '.':
        fs_path = directory[1:] if directory.startswith('/') else directory
        full_dir = os.path.join(UPLOAD_FOLDER, fs_path)
    else:
        full_dir = UPLOAD_FOLDER
    
    full_path = os.path.join(full_dir, filename)
    
    if not os.path.exists(full_path):
        collection.delete_one({"_id": file_doc["_id"]})
        flash("File not found on disk.", "danger")
        return redirect(url_for("index"))
    
    return send_from_directory(full_dir, filename)

@app.route("/preview")
@login_required
def preview():
    """Preview file using query parameters"""
    user = session.get("user")
    filename = request.args.get("filename", "").strip()
    path = request.args.get("path", "").strip()
    
    if not filename:
        flash("No file specified.", "danger")
        return redirect(url_for("index"))
    
    # Find the file
    query = {"uploaded_by": user, "filename": filename, "is_folder": False}
    
    if path:
        query["path"] = path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    file_doc = collection.find_one(query)
    
    if not file_doc:
        # Try with original_filename
        query = {"uploaded_by": user, "original_filename": filename, "is_folder": False}
        if path:
            query["path"] = path
        else:
            query["path"] = {"$in": ["", None, "/"]}
        file_doc = collection.find_one(query)
    
    if not file_doc:
        flash("File not found or access denied.", "danger")
        return redirect(url_for("index", path=path))
    
    # Get filesystem path
    file_path = get_file_path(file_doc)
    
    if not os.path.exists(file_path):
        collection.delete_one({"_id": file_doc["_id"]})
        flash("File not found on disk.", "danger")
        return redirect(url_for("index", path=path))
    
    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    
    return send_from_directory(directory, filename)

@app.route("/view")
@login_required
def view():
    """View file details page"""
    user = session.get("user")
    filename = request.args.get("filename", "").strip()
    path = request.args.get("path", "").strip()
    
    if not filename:
        flash("No file specified.", "danger")
        return redirect(url_for("index"))
    
    # Find the file
    query = {"uploaded_by": user, "filename": filename, "is_folder": False}
    
    if path:
        query["path"] = path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    file_doc = collection.find_one(query)
    
    if not file_doc:
        # Try with original_filename
        query = {"uploaded_by": user, "original_filename": filename, "is_folder": False}
        if path:
            query["path"] = path
        else:
            query["path"] = {"$in": ["", None, "/"]}
        file_doc = collection.find_one(query)
    
    if not file_doc:
        flash("File not found or access denied.", "danger")
        return redirect(url_for("index", path=path))
    
    # Get file info
    file_path = get_file_path(file_doc)
    file_size = 0
    file_size_readable = "Unknown"
    
    if os.path.exists(file_path):
        try:
            file_size = os.path.getsize(file_path)
            file_size_readable = format_size(file_size)
        except OSError:
            pass
    
    # Get mime type for preview
    mime_type, _ = mimetypes.guess_type(filename)
    
    return render_template("viewer.html", 
                         file=file_doc,
                         filename=filename,
                         path=path,
                         file_size=file_size_readable,
                         mime_type=mime_type)

@app.route("/delete", methods=["POST"])
@login_required
def delete():
    """Delete a file"""
    user = session.get("user")
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "message": "Invalid request"}), 400
    
    filename = data.get("filename", "").strip()
    path = data.get("path", "").strip()
    
    if not filename:
        return jsonify({"success": False, "message": "No file specified."}), 400
    
    # Find the file
    query = {"uploaded_by": user, "filename": filename, "is_folder": False}
    
    if path:
        query["path"] = path
    else:
        query["path"] = {"$in": ["", None, "/"]}
    
    file_doc = collection.find_one(query)
    
    if not file_doc:
        return jsonify({"success": False, "message": "File not found or access denied"}), 404
    
    # Delete from filesystem
    file_path = get_file_path(file_doc)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError as e:
        return jsonify({"success": False, "message": f"Error deleting file: {str(e)}"}), 500
    
    # Delete from database
    collection.delete_one({"_id": file_doc["_id"]})
    
    return jsonify({"success": True, "message": "File deleted successfully!"})

@app.route("/api/create-folder", methods=["POST"])
@login_required
def create_folder():
    user = session.get("user")
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "message": "Invalid request"}), 400
    
    folder_name = data.get("folder_name", "").strip()
    parent_path = data.get("path", "").strip()
    
    if not folder_name:
        return jsonify({"success": False, "message": "Folder name is required."}), 400
    
    # Sanitize folder name
    folder_name = secure_filename(folder_name)
    if not folder_name:
        return jsonify({"success": False, "message": "Invalid folder name."}), 400
    
    # Normalize parent path
    if parent_path and not parent_path.startswith("/"):
        parent_path = "/" + parent_path
    if parent_path.endswith("/") and parent_path != "/":
        parent_path = parent_path.rstrip("/")
    
    # Check if folder already exists
    existing = collection.find_one({
        "uploaded_by": user, 
        "path": parent_path if parent_path else "",
        "is_folder": True, 
        "name": folder_name
    })
    
    if existing:
        return jsonify({"success": False, "message": "Folder already exists."}), 400
    
    # Create physical folder
    if parent_path and parent_path != "/":
        # Remove leading slash for filesystem
        rel_path = parent_path[1:] if parent_path.startswith('/') else parent_path
        folder_path = os.path.join(UPLOAD_FOLDER, rel_path, folder_name)
    else:
        folder_path = os.path.join(UPLOAD_FOLDER, folder_name)
    
    os.makedirs(folder_path, exist_ok=True)
    
    # Create folder document
    folder_doc = {
        "name": folder_name,
        "path": parent_path if parent_path else "",
        "is_folder": True,
        "upload_time": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "uploaded_by": user
    }
    
    collection.insert_one(folder_doc)
    return jsonify({"success": True, "message": "Folder created successfully."})

@app.route("/api/delete-folder", methods=["POST"])
@login_required
def delete_folder():
    user = session.get("user")
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "message": "Invalid request"}), 400
    
    folder_name = data.get("folder_name", "").strip()
    parent_path = data.get("path", "").strip()
    
    if not folder_name:
        return jsonify({"success": False, "message": "Folder name is required."}), 400
    
    # Find folder
    folder_doc = collection.find_one({
        "uploaded_by": user, 
        "path": parent_path if parent_path else "",
        "is_folder": True, 
        "name": folder_name
    })
    
    if not folder_doc:
        return jsonify({"success": False, "message": "Folder not found."}), 404
    
    # Check if folder is empty
    folder_full_path = f"{parent_path}/{folder_name}" if parent_path else f"/{folder_name}"
    if folder_full_path.startswith('//'):
        folder_full_path = folder_full_path[1:]
    
    items_in_folder = collection.count_documents({
        "uploaded_by": user, 
        "path": folder_full_path
    })
    
    if items_in_folder > 0:
        return jsonify({"success": False, "message": "Folder is not empty. Delete all files first."}), 400
    
    # Delete physical folder
    if parent_path and parent_path != "/":
        rel_path = parent_path[1:] if parent_path.startswith('/') else parent_path
        folder_path = os.path.join(UPLOAD_FOLDER, rel_path, folder_name)
    else:
        folder_path = os.path.join(UPLOAD_FOLDER, folder_name)
    
    try:
        if os.path.exists(folder_path):
            os.rmdir(folder_path)
    except OSError as e:
        return jsonify({"success": False, "message": f"Error deleting folder: {str(e)}"}), 500
    
    # Delete from database
    collection.delete_one({"_id": folder_doc["_id"]})
    return jsonify({"success": True, "message": "Folder deleted successfully."})

@app.route('/debug/paths')
@login_required
def debug_paths():
    """Debug endpoint to check file paths"""
    user = session.get('user')
    filename = request.args.get('filename', '')
    path = request.args.get('path', '')
    
    result = {
        'user': user,
        'filename': filename,
        'path': path,
        'upload_folder': UPLOAD_FOLDER,
        'upload_folder_exists': os.path.exists(UPLOAD_FOLDER),
    }
    
    if filename:
        query = {"uploaded_by": user, "filename": filename}
        if path:
            query["path"] = path
        else:
            query["path"] = {"$in": ["", None, "/"]}
        
        file_doc = collection.find_one(query)
        result['db_found'] = file_doc is not None
        
        if file_doc:
            result['db_doc'] = {
                'filename': file_doc.get('filename'),
                'path': file_doc.get('path'),
                'original_filename': file_doc.get('original_filename')
            }
            
            # Calculate filesystem path
            fs_path = get_file_path(file_doc)
            result['filesystem_path'] = fs_path
            result['filesystem_exists'] = os.path.exists(fs_path)
            
            if os.path.exists(fs_path):
                result['filesystem_size'] = os.path.getsize(fs_path)
    
    return jsonify(result)

if __name__ == "__main__":
    print(f"Starting Cloud File Storage Server on http://0.0.0.0:5000")
    print(f"Upload folder: {UPLOAD_FOLDER}")
    app.run(host="0.0.0.0", port=5000, debug=True)