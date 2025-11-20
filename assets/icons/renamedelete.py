import os

def rename_and_delete_files_in_folder(folder_path):
    """
    Iterates through all files in the given folder and applies:
    - Rename each file by adding a prefix 'processed_'.
    - Delete any file that is empty (size = 0 bytes).
    """
    if not os.path.isdir(folder_path):
        print(f"The folder '{folder_path}' does not exist.")
        return

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        # Skip directories
        if os.path.isdir(file_path):
            continue

        # Delete empty files
        if os.path.getsize(file_path) == 0:
            os.remove(file_path)
            print(f"Deleted empty file: {filename}")
            continue

        # Rename file
        new_filename = f"processed_{filename}"
        new_file_path = os.path.join(folder_path, new_filename)
        os.rename(file_path, new_file_path)
        print(f"Renamed file: {filename} -> {new_filename}")

# Use the folder where this script is located
current_folder = os.path.dirname(os.path.abspath(__file__))
rename_and_delete_files_in_folder(current_folder)