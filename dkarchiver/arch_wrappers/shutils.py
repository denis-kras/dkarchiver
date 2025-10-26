import os
import shutil
from pathlib import Path


def extract_archive_with_shutil(file_path: str, target_directory: str) -> str:
    """
    Function extracts the archive to target directory.
    Returns full path to extracted directory.
    This function doesn't preserve the original date and time of files from the archive, instead the time of extraction
    will be applied.

    :param file_path: Full file path to archived file to extract.
    :param target_directory: The directory on the filesystem to extract the file to.
    :return: str.
    """

    print(f'Extracting {file_path}')

    shutil.unpack_archive(file_path, target_directory)
    file_stem: str = Path(file_path).stem
    extracted_directory: str = f'{target_directory}{os.sep}{file_stem}'

    print(f'Extracted to: {extracted_directory}')
    return extracted_directory
