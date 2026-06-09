import os
import shutil

def clean_pycache():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Cleaning __pycache__ in: {project_dir}")
    removed_dirs = 0
    removed_files = 0
    
    for root, dirs, files in os.walk(project_dir, topdown=False):
        # Ignore virtual environments like .venv
        if ".venv" in root.split(os.sep):
            continue
            
        for d in dirs:
            if d == "__pycache__":
                path = os.path.join(root, d)
                try:
                    shutil.rmtree(path)
                    print(f"Removed directory: {path}")
                    removed_dirs += 1
                except Exception as e:
                    print(f"Failed to remove directory {path}: {e}")

        for f in files:
            if f.endswith((".pyc", ".pyo")):
                path = os.path.join(root, f)
                try:
                    os.remove(path)
                    print(f"Removed file: {path}")
                    removed_files += 1
                except Exception as e:
                    print(f"Failed to remove file {path}: {e}")

    print(f"Clean complete. Removed {removed_dirs} directories and {removed_files} files.")

if __name__ == "__main__":
    clean_pycache()
