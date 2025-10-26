import os
import time
import zipfile
from io import BytesIO
from typing import Union, Literal
from pathlib import Path
import shutil


def is_zip_zipfile(file_object: Union[str, bytes]) -> bool:
    """
    Function checks if the file is a zip file.
    :param file_object: can be two types:
        string, full path to the file.
        bytes or BytesIO, the bytes of the file.
    :return: boolean.
    """

    try:
        if isinstance(file_object, bytes):
            with BytesIO(file_object) as file_object:
                with zipfile.ZipFile(file_object) as zip_object:
                    zip_object.testzip()
                    return True
        elif isinstance(file_object, str):
            with zipfile.ZipFile(file_object) as zip_object:
                zip_object.testzip()
                return True
        else:
            raise TypeError("file_object must be of type 'str' or 'bytes'.")
    except zipfile.BadZipFile:
        return False


def is_zip_magic_number(file_path: str) -> bool:
    """
    Function checks if the file is a zip file using magic number.
    :param file_path: string, full path to the file.
    :return: boolean.

    50 4B 03 04: This is the most common signature, found at the beginning of a ZIP file.
        It signifies the start of a file within the ZIP archive and is present in almost all ZIP files.
        Each file within the ZIP archive starts with this signature.
    50 4B 05 06: This is the end of central directory record signature.
        It's found at the end of a ZIP file and is essential for identifying the structure of the ZIP archive,
        especially in cases where the file is split or is a multipart archive.
    50 4B 07 08: This signature is used for spanned ZIP archives (also known as split or multi-volume ZIP archives).
        It's found in the end of central directory locator for ZIP files that are split across multiple volumes.
    """

    with open(file_path, 'rb') as file:
        # Read the first 4 bytes of the file
        signature = file.read(4)

    # Check if the signature matches any of the ZIP signatures
    return signature in [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08']


def extract_archive_with_zipfile(
        archive_path: str,
        extract_directory: str = None,
        files_without_directories: bool = False,
        remove_first_directory: bool = False
) -> str:
    """
    Function will extract the archive using standard library 'zipfile'.
    This method preserves original date and time of the files inside the archive.

    :param archive_path: string, full path to archived file.
    :param extract_directory: string, full path to directory that the files will be extracted to.
        If not specified, the files will be extracted to the same directory as the archived file, using the file name
        without extension as the directory name.
    :param files_without_directories: boolean, default 'False'.
        'True': All the files in the archive will be extracted without subdirectories hierarchy.
            Meaning, that if there are duplicate file names, the latest file with the same file name will overwrite
            all the rest of the files with the same name.
        'False': Subdirectory hierarchy will be preserved as it is currently in the archived file.
    :param remove_first_directory: boolean, default is 'False'.
        'True': all the files will be extracted without first directory in the hierarchy.
            Example: package_some_name_1.1.1_build/subdir1/file.exe
            Will be extracted as: subdir/file.exe

    :return: string, full path to directory that the files were extracted to.
    """

    # If 'extract_directory' is not specified, extract to the same directory as the archived file.
    if extract_directory is None:
        extract_directory = str(Path(archive_path).parent / Path(archive_path).stem)

    print(f'Extracting to directory: {extract_directory}')

    # initiating the archived file path as 'zipfile.ZipFile' object.
    with zipfile.ZipFile(archive_path) as zip_object:
        # '.infolist()' method of the object contains all the directories and files that are in the archive including
        # information about each one, like date and time of archiving.
        for zip_info in zip_object.infolist():
            # '.filename' attribute of the 'infolist()' method is relative path to each directory and file.
            # If 'filename' ends with '/' it is a directory (it doesn't matter if it is windows or *nix)
            # If so, skip current iteration.
            if zip_info.filename[-1] == '/':
                continue

            if files_without_directories:
                # Put into 'filename' the string that contains only the filename without subdirectories.
                zip_info.filename = os.path.basename(zip_info.filename)
            elif remove_first_directory:
                # Cut the first directory from the filename.
                zip_info.filename = zip_info.filename.split('/', maxsplit=1)[1]

            print(f'Extracting: {zip_info.filename}')

            # Extract current file from the archive using 'zip_info' of the current file with 'filename' that we
            # updated under specified parameters to specified directory.
            zip_object.extract(zip_info, extract_directory)

            # === Change the date and time of extracted file from current time to the time specified in 'zip_info'.
            # Get full path to extracted file.
            extracted_file_path: str = extract_directory + os.sep + zip_info.filename
            # Create needed datetime object with original archived datetime from 'zip_info.date_time'.
            date_time = time.mktime(zip_info.date_time + (0, 0, -1))
            # Using 'os' library, changed the datetime of the file to the object created in previous step.
            os.utime(extracted_file_path, (date_time, date_time))
    print('Extraction done.')

    return extract_directory


def get_file_list_from_zip(file_path: str) -> list:
    """
    Function returns the list of file names and their relative directories inside the zip file.
    :param file_path: string, full path to the zip file.
    :return: list of strings.
    """

    with zipfile.ZipFile(file_path, 'r') as zip_object:
        return zip_object.namelist()


def archive_directory(
        directory_path: str,
        compression: Literal[
            'store',
            'deflate',
            'bzip2',
            'lzma'] = 'deflate',
        include_root_directory: bool = True,
        remove_original: bool = False
) -> str:
    """
    Function archives the directory.
    :param directory_path: string, full path to the directory.
    :param compression: string, default is 'deflate'.
        'store': No compression.
        'deflate': Standard ZIP compression.
        'bzip2': BZIP2 compression.
            Provides better compression than Deflate but is typically slower. This method might not be supported by
            all ZIP utilities.
        'lzma': LZMA compression.
            high compression ratios but is also slower compared to Deflate. This method is less commonly used and
            may not be supported by all ZIP utilities.
    :param include_root_directory: boolean, default is 'True'.
        'True': The root directory will be included in the archive.
        'False': The root directory will not be included in the archive.
        True is usually the case in most archiving utilities.
    :param remove_original: boolean, default is 'False'. If 'True', the original directory will be removed.
    :return: string, full path to the archived file.
    """

    if compression == 'store':
        compression_method = zipfile.ZIP_STORED
    elif compression == 'deflate':
        compression_method = zipfile.ZIP_DEFLATED
    elif compression == 'bzip2':
        compression_method = zipfile.ZIP_BZIP2
    elif compression == 'lzma':
        compression_method = zipfile.ZIP_LZMA
    else:
        raise ValueError(f"Unsupported compression method: {compression}")

    archive_path: str = directory_path + '.zip'
    with zipfile.ZipFile(archive_path, 'w', compression_method) as zip_object:
        for root, _, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)

                # If including the root directory, use the relative path from the parent directory of the root
                if include_root_directory:
                    arcname = os.path.relpath(file_path, os.path.dirname(directory_path))
                else:
                    arcname = os.path.relpath(file_path, directory_path)

                zip_object.write(file_path, arcname)

    if remove_original:
        shutil.rmtree(directory_path, ignore_errors=True)

    return archive_path
