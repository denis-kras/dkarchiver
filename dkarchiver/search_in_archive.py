import os
import zipfile
from io import BytesIO
from typing import Union
from typing import Callable, Optional

from .arch_wrappers import zips, sevenzs
from .helper import file_types

import py7zr


SUPPORTED_ARCHIVE_MIMES: list = [
    'application/x-7z-compressed',
    'application/zip',
    'application/x-dosexec',      # SFX zip files.
    'application/octet-stream',    # There are some non-standard zip files that are not recognized by magic.
    'application/vnd.microsoft.portable-executable'     # PE files. Some self extracting archives are PE files, But the zip module can handle them.
]


# Custom exception if the file is not known archive type.
class UnknownArchiveType(Exception):
    pass


try:
    from py7zr import Py7zIO, WriterFactory  # py7zr >= 1.0
except ImportError:
    Py7zIO = object
    WriterFactory = object


class _MemIO(Py7zIO):
    def __init__(self):
        self._buf = BytesIO()
    def write(self, b: bytes):
        self._buf.write(b)
    # read/seek/flush/size are used by the API examples and keep this compatible
    def read(self, size: Optional[int] = None) -> bytes:
        data = self._buf.getvalue()
        return data if size is None else data[:size]
    def seek(self, offset: int, whence: int = 0) -> int:
        return self._buf.seek(offset, whence)
    def flush(self) -> None:
        pass
    def size(self) -> int:
        return len(self._buf.getvalue())


class _MemFactory(WriterFactory):
    def __init__(self):
        self.products = {}  # filename -> _MemIO
    def create(self, filename: str) -> Py7zIO:
        obj = _MemIO()
        self.products[filename] = obj
        return obj


def _read_7z_member_bytes(arch_obj, name: str) -> bytes:
    # Backward compatibility (py7zr < 1.0.0)
    if hasattr(arch_obj, "read"):
        data = arch_obj.read([name])
        try:
            return data[name].read()
        finally:
            arch_obj.reset()
    # py7zr >= 1.0.0: use extract(..., factory=...)
    factory = _MemFactory()
    targets = [name]
    # py7zr quirk: when targeting 'dir/file', include parent dir too
    if "/" in name:
        top = name.split("/", 1)[0]
        if top and top != name:
            targets = [top, name]  # see API docs note below
    arch_obj.extract(targets=targets, factory=factory)
    try:
        return factory.products[name].read()
    finally:
        arch_obj.reset()


def _get_unique_filename(directory, filename):
    """
    Generates a unique filename by appending a number if the file already exists.
    """
    name, ext = os.path.splitext(filename)
    counter = 1
    unique_filename = filename
    while os.path.exists(os.path.join(directory, unique_filename)):
        unique_filename = f"{name}_{counter}{ext}"
        counter += 1
    return unique_filename


def _match_file_name(target, current, case_sensitive):
    if case_sensitive:
        return current.endswith(target)
    else:
        return current.lower().endswith(target.lower())


def _handle_file_extraction(item, extract_file_to_path, archived_file_bytes):
    if extract_file_to_path:
        unique_filename = _get_unique_filename(extract_file_to_path, os.path.basename(item.filename))
        with open(os.path.join(extract_file_to_path, unique_filename), 'wb') as f:
            f.write(archived_file_bytes)


def _handle_callback_matching(
        item, archive_type, archived_file_bytes, callback_functions, results, found_set, return_first_only):
    for callback in callback_functions:
        callback_result = callback(archived_file_bytes)
        if callback_result:
            # Initialize key for callback function name if not present
            if _get_callback_name(callback) not in results:
                results[_get_callback_name(callback)]: dict = {}
                results[_get_callback_name(callback)]['files']: list = []

            if archive_type == 'zip':
                file_info = {
                    'bytes': archived_file_bytes,
                    'name': item.filename,
                    'size': item.file_size,
                    'modified_time': item.date_time
                }
            elif archive_type == '7z':
                file_info = {
                    'bytes': archived_file_bytes,
                    'name': item.filename,
                    'size': item.uncompressed,
                    'modified_time': item.creationtime
                }
            else:
                raise UnknownArchiveType(f"Unknown archive type: {archive_type}")

            results[_get_callback_name(callback)]['files'].append(file_info)
            results[_get_callback_name(callback)]['callable_result'] = callback_result
            if return_first_only:
                found_set.add(item.filename)
            return True
    return False


def _handle_name_matching(item, archived_file_bytes, file_names, case_sensitive, results, found_set, return_first_only):
    if any(_match_file_name(file_name, item.filename, case_sensitive) for file_name in file_names):
        if item.filename not in results:
            results[item.filename] = []
        file_info = {
            'bytes': archived_file_bytes,
            'name': item.filename,
            'size': item.file_size,
            'modified_time': item.date_time
        }
        results[item.filename].append(file_info)
        if return_first_only:
            found_set.add(item.filename)


def _search_in_archive(
        arch_obj, archive_type, file_names, results, found_set, case_sensitive, return_first_only, recursive,
        callback_functions, extract_file_to_path):
    file_info_list = None
    if archive_type == 'zip':
        file_info_list = arch_obj.infolist()
    elif archive_type == '7z':
        file_info_list = arch_obj.list()

    # Iterate over each file in the archive.
    for item_index, item in enumerate(file_info_list):
        # At this stage we will get the bytes of the archived file, which is an 'item' in the archive.
        archived_file_bytes = None
        # If the main archive is zip we will use the 'open' method, if it's 7z we will use the 'read' method.
        if archive_type == 'zip':
            # Skip directories.
            if item.filename.endswith('/'):
                continue

            with arch_obj.open(item) as file_data:
                archived_file_bytes = file_data.read()
        elif archive_type == '7z':
            # Skip directories.
            if item.is_directory:
                continue

            archived_file_bytes = _read_7z_member_bytes(arch_obj, item.filename)

        # After we get the file bytes we will check if the file matches the callback functions.
        callback_matched = False
        if callback_functions:
            callback_matched = _handle_callback_matching(
                item, archive_type, archived_file_bytes, callback_functions, results, found_set, return_first_only)

        if callback_matched:
            _handle_file_extraction(item, extract_file_to_path, archived_file_bytes)
        else:
            if recursive and (zips.is_zip_zipfile(archived_file_bytes) or sevenzs.is_7z_magic_number(archived_file_bytes)):
                _search_archive_content(
                    archived_file_bytes, file_names, results, found_set, case_sensitive, return_first_only,
                    recursive, callback_functions, extract_file_to_path)
            if file_names and not callback_matched:
                _handle_name_matching(
                    item, archived_file_bytes, file_names, case_sensitive, results, found_set, return_first_only)

        if file_names is not None and len(found_set) == len(file_names):
            break  # All files found, stop searching


def _get_callback_name(callback: Callable) -> str:
    """
    Get the name of the callback function.
    :param callback: callable.
    :return: string, the name of the callback function. If the function is part of the class, the name will be
        'class_name.function_name'; if not, only the function name will be returned.
    """
    try:
        # noinspection PyUnresolvedReferences
        class_name = callback.__self__.__class__.__name__
    except AttributeError:
        class_name = None

    function_name = callback.__name__

    if class_name:
        return f"{class_name}.{function_name}"
    else:
        return function_name


def _get_archive_type(file_object) -> Union[str, None]:
    file_mime: str = file_types.get_mime_type(file_object)

    if file_mime not in SUPPORTED_ARCHIVE_MIMES:
        return None

    if zips.is_zip_zipfile(file_object):
        return 'zip'
    elif sevenzs.is_7z_magic_number(file_object):
        return '7z'
    else:
        raise UnknownArchiveType(f"{file_object[:10]} is not a known archive type.")


def _search_archive_content(
        file_object, file_names_to_search, results, found_set, case_sensitive, return_first_only, recursive,
        callback_functions, extract_file_to_path):
    archive_type = _get_archive_type(file_object)

    if isinstance(file_object, str):
        if archive_type == 'zip':
            with zipfile.ZipFile(file_object, 'r') as archive_ref:
                _search_in_archive(
                    archive_ref, archive_type, file_names_to_search, results, found_set, case_sensitive,
                    return_first_only, recursive, callback_functions, extract_file_to_path)
        elif archive_type == '7z':
            with py7zr.SevenZipFile(file_object, 'r') as archive_ref:
                _search_in_archive(
                    archive_ref, archive_type, file_names_to_search, results, found_set, case_sensitive,
                    return_first_only, recursive, callback_functions, extract_file_to_path)
    elif isinstance(file_object, bytes):
        if archive_type == 'zip':
            with BytesIO(file_object) as file_like_object:
                with zipfile.ZipFile(file_like_object, 'r') as archive_ref:
                    _search_in_archive(
                        archive_ref, archive_type, file_names_to_search, results, found_set, case_sensitive,
                        return_first_only, recursive, callback_functions, extract_file_to_path)
        elif archive_type == '7z':
            with BytesIO(file_object) as file_like_object:
                with py7zr.SevenZipFile(file_like_object, 'r') as archive_ref:
                    _search_in_archive(
                        archive_ref, archive_type, file_names_to_search, results, found_set, case_sensitive,
                        return_first_only, recursive, callback_functions, extract_file_to_path)


def search_file_in_archive(
        file_object: Union[str, bytes] = None,
        file_names_to_search: list[str] = None,
        case_sensitive: bool = True,
        return_first_only: bool = False,
        return_empty_list_per_file_name: bool = False,
        recursive: bool = False,
        callback_functions: list = None,
        extract_file_to_path: str = None
) -> dict[list[bytes], str]:
    """
    Function searches for the file names inside the zip file and returns a dictionary where the keys are the
    names of the callback functions and the values are lists of found file bytes.
    :param file_object: it can be two types:
        string, full path to the zip file.
        bytes, the bytes of the zip file.
    :param file_names_to_search: list of strings, the names of the files to search.
    :param case_sensitive: boolean, default is 'True'. Determines if file name search should be case sensitive.
    :param return_first_only: boolean, default is 'False'. Return only the first found file for each file name.
    :param return_empty_list_per_file_name: boolean, default is 'False'.
        True: Return empty list for each file name that wasn't found.
        False: Don't return empty list for each file name that wasn't found.
    :param recursive: boolean, default is 'False'. If True, search for file names recursively in nested zip files.
    :param callback_functions: list of callables, default is None. Each function takes a file name and should return a
        boolean that will tell the main function if this file is 'found' or not.
    :param extract_file_to_path: string, full path to the directory where the found files should be extracted.
    :return: dictionary of lists of bytes.
    """

    if file_names_to_search is None and callback_functions is None:
        raise ValueError("Either file_names_to_search or callback_functions must be provided.")

    # Initialize results dictionary.
    results: dict[list[bytes], str] = {}
    found_set = set()

    _search_archive_content(
        file_object, file_names_to_search, results, found_set, case_sensitive, return_first_only, recursive,
        callback_functions, extract_file_to_path)

    if not return_empty_list_per_file_name:
        # Filter out keys with empty lists.
        results = {key: value for key, value in results.items() if value}

    return results
