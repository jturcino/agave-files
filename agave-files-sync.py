#!/usr/bin/env python

import argparse
from os.path import expanduser, isfile, isdir, basename, getmtime
from json import load, loads, dumps
from requests import get, post, put
from os import makedirs, listdir 
from datetime import datetime

# global variables
cache = '~/.agave/current'
agave_prefix='agave://'
url_prefix='http'

# file types; set here to avoid repeated string use
agave = 'agave'
url = 'url'
local = 'local'

# basic helper functions
def get_path_type(path):
    '''Determines if path is of local, agave, or url types.'''
    path_type=''
    if path[:len(agave_prefix)] == agave_prefix:
        path_type = agave
    elif path[:len(url_prefix)] == url_prefix:
        path_type = url
    else:
        assert isfile(path) or isdir(path), 'Invalid local path: {}'.format(path)
        path_type = local
    return path_type

def agave_path_builder(base, path, recursive=False):
    '''Generates a ready-to-use agave url with the cached base and user-provided path'''
    assert get_path_type(path) == agave, 'Path is type {}, must be type agave'.format(get_path_type(path))
    # strip agave prefix
    path = path[len(agave_prefix): ]
    # return full path
    path = '{}/files/v2/media/system/{}'.format(base, path)
    return path

def agave_path_setlisting(path, base, listings=True):
    '''Sets path prefix to /files/v2/listings/ when listings=True (default) and /files/v2/media/ when listings=False'''
    if listings:
        path = path.replace('{}/files/v2/media'.format(base), '{}/files/v2/listings'.format(base))
    else:
        path = path.replace('{}/files/v2/listings'.format(base), '{}/files/v2/media'.format(base))
    return path

def sametype(local_filepath, agave_description):
    '''Checks if local and agave files are both directories or files. Returns boolean.'''
    return (isfile(local_filepath) and agave_description['type'] == 'file') or (isdir(local_filepath) and agave_description['type'] == 'dir')

def update_import_destfiles_dict(new_dest, headers, url_base):
    '''Helper function to update dictionary of destination file information'''
    new_dest = agave_path_setlisting(new_dest, url_base) # get list url
    fdict = { i['name']: {'lastModified':i['lastModified'], 'type':i['type'], 'path':i['path']}
               for i in list_agave_dir_files(new_dest, headers) }
    return fdict
# end basic helper functions

# request wrappers
def list_agave_dir_files(url, headers):
    '''Performs files-list on remote agave directory and returns list of file JSON descriptions'''
    r = get(url, headers=headers)
    assert r.status_code == 200, 'Unable to list files at {}; status code {}'.format(url, r.status_code)
    l = loads(r.content)
    assert l.get('result') is not None, 'Unable to read file info from key "result" in JSON \n{}'.format(dumps(l, indent=2))
    return l['result']

def files_download(url, headers, path='.', name=None):
    '''Downloads and saves file at url. Defaults to saving in the current directory without changing name, but these options are available.'''
    r = get(url, headers=headers)
    assert r.status_code == 200, 'files-download failed with code {}'.format(r.status_code)
    # set up path
    if name is None:
        name = basename(url)
    path += '/'+name
    with open(expanduser(path), 'wb') as f:
        f.write(r.content)
    return

def files_upload(localfile, url, headers, new_name=None):
    '''Uploads file at localfile path to url. Name at location can be specified with new_name; defaults to current name.'''
    assert isfile(localfile), 'Local file {} does not exists or is directory'.format(localfile)
    # set new_name to current name if not given
    if new_name is None:
        new_name = basename(localfile)
    # format file data and run command
    files = {'fileToUpload': (new_name, open(expanduser(localfile), 'rb'))}
    r = post(url, headers=headers, files=files)
    assert r.status_code == 202, 'Command status code is {}, not 202'.format(r.status_code)
    return

def files_mkdir(dirname, url, headers):
    '''Makes a directory at the agave url path.'''
    data = {'action': 'mkdir', 'path':dirname}
    r = put(url+'/', data=data, headers=headers)
    assert r.status_code == 201, 'Mkdir status_code was {}'.format(r.status_code)
    return

def files_import(source, destination, headers, new_name=None):
    '''Import file from remote source to remote destination. New name defaults to current name.'''
    if new_name is None:
        new_name = basename(source)
    data = {'urlToIngest': source, 'fileName': new_name}
    r = post(destination, headers=headers, data=data)
    assert r.status_code == 202, 'Command status code is {}, not 202'.format(r.status_code)
    return
# end request wrappers

# modification time helper functions
def get_localfile_modtime(localfile):
    '''Given path to file, returns datetime of last modification on that file.'''
    assert isfile(localfile) or isdir(localfile), 'Local file {} does not exist'.format(localfile)
    return datetime.fromtimestamp(getmtime(localfile))

def get_agavefile_modtime(agavedescription):
    '''Given Agave file JSON file description (only lastModified key required), returns datetime of last modification on that file.'''
    assert 'lastModified' in agavedescription, 'lastModified key not in Agave description keys: {}'.format(agavedescription.keys())
    # strip '.000-0X:00' off modtime (unknown meaning)
    modstring = agavedescription['lastModified'][:-10] 
    strptime_format = '%Y-%m-%dT%H:%M:%S'
    return datetime.strptime(modstring, strptime_format)

def newer_agavefile(localfile, agavedescription):
    '''Given local filepath and Agave file JSON description (only lastModified key required), return TRUE if Agave file is more recently modified.'''
    assert isfile(localfile) or isdir(localfile), 'Local file {} does not exist'.format(localfile)
    assert 'lastModified' in agavedescription, 'lastModified key not in Agave description keys: {}'.format(agavedescription.keys())
    local_modtime = get_localfile_modtime(localfile)
    agave_modtime = get_agavefile_modtime(agavedescription)
    return (agave_modtime > local_modtime)

def newer_importfile(import_description, dest_description):
    '''Given import and destination Agave file JSON descriptions (only lastModified key required), return TRUE if import file is more recently modified.'''
    assert 'lastModified' in import_description, 'lastModified key not in import description keys: {}'.format(import_description.keys())
    assert 'lastModified' in dest_description, 'lastModified key not in destination description keys: {}'.format(dest_description.keys())
    import_modtime = get_agavefile_modtime(import_description)
    dest_modtime = get_agavefile_modtime(dest_description)
    return(import_modtime > dest_modtime)
# end modification time helper functions

# recursive files functions
def recursive_get(url, headers, url_base, destination='.', skipdir=False, tab=''):
    '''Performs recursive files-get from remote to local location (ONLY AGAVE CURRENTLY SUPPORTED)'''
    # get listable url and file-list
    list_url = agave_path_setlisting(url, url_base)
    list_json = list_agave_dir_files(list_url, headers)

    for i in list_json:
        filename = i['name']

        # if is directory and '.': mkdir if necessary, otherwise skip
        if i['type'] == 'dir' and filename == '.':
            directoryname = basename(i['path'])
            if skipdir: # if skip is set, pass without change
                print(tab+'skipping', directoryname, '(matching with {})'.format(destination))
            else: # set new destination; make dir if necessary
                destination += '/{}'.format(directoryname) # add dirname to local path
                if isdir(destination):
                    print(tab+'skipping', directoryname, '(exists)')
                else:
                    print(tab+'mkdir', destination)
                    makedirs(destination)
            tab += '  '

        # elif is not '.' but still directory, recurse
        elif i['type'] == 'dir':
            recursion_url = '{}/{}'.format(url,filename)
            recursive_get(recursion_url, headers, url_base, destination=destination, tab=tab)

        # must be file; download if not in local dir (new) or agave timestamp is newer (modified), otherwise skip
        else:
            # build file url by adding filename
            file_url = '{}/{}'.format(url, filename)
            filename_fullpath = '{}/{}'.format(destination, filename)
            if filename not in listdir(destination):
                print(tab+'downloading', filename, '(new)')
                files_download(file_url, headers, path=destination)
            elif newer_agavefile(filename_fullpath, i):
                print(tab+'downloading', filename, '(modified)')
                files_download(file_url, headers, path=destination)
            else:
                print(tab+'skipping', filename, '(exists)')
    return

def recursive_upload(url, headers, url_base, source='.', skipdir=False, urlinfo={}, tab=''):
    '''Recursively upload files from a local directory to an agave directory'''
    assert url[-1] != '/', 'Provided url cannot have trailing slashe: {}'.format(url)
    assert source[-1] != '/', 'Provided source cannot have trailing slash: {}'.format(source)

    # make agave url listable
    list_url = agave_path_setlisting(url, url_base, listings=True)

    # if no previous agave files provided, list
    if len(urlinfo) == 0:
        urlfiles = list_agave_dir_files(list_url, headers)
        urlinfo = {i['name']:{'lastModified':i['lastModified'],'type':i['type']} for i in urlfiles}
        assert '.' in urlinfo, 'Url {} is not valid directory: {}'.format(url)

    # check base dir: skip if matching, make if missing, ignore if already exists
    dirname = basename(source)
    if skipdir:
        print(tab+'skipping', dirname, '(matching with {})'.format(basename(url)))
    else: # mkdir if needed, then update urls and current files
        if dirname not in urlinfo:
            print(tab+'mkdir', dirname, '(new)')
            files_mkdir(dirname, url, headers)
        url += '/{}'.format(dirname)
        list_url += '/{}'.format(dirname)
        urlfiles = list_agave_dir_files(list_url, headers)
        urlinfo = {i['name']:{'lastModified':i['lastModified'],'type':i['type']} for i in urlfiles}
        assert '.' in urlinfo, 'url {} is not valid directory'.format(url)

    # process files between remote and agave directories
    for filename in listdir(expanduser(source)):
        fullpath = (expanduser(source) if filename == '.' else '{}/{}'.format(expanduser(source), filename))
        # if local file present at dest: skip if is dir or if agavefile is newer, else upload file
        if filename in urlinfo and sametype(fullpath, urlinfo[filename]):
            if isdir(fullpath) or newer_agavefile(fullpath, urlinfo[filename]):
                print(tab+'  skipping', filename, '(exists)')
            else:
                print(tab+'  uploading', filename, '(modified)')
                files_upload(fullpath, url, headers)
        # if local file is new, upload file
        elif isfile(fullpath):
            print(tab+'  uploading', filename, '(new)')
            files_upload(fullpath, url, headers)

        # if is directory (newly made or old), recurse
        if isdir(fullpath):
            recursive_upload(url, headers, url_base, source=fullpath, urlinfo=urlinfo, tab=tab+'  ')
    return

def recursive_import(source, destination, headers, url_base, skipdir=False, dfiles={}, tab=''):
    '''Performs recursive files-import between remote agave locations.'''
    # get source list url
    slisturl = agave_path_setlisting(source, url_base)

    # get dict of destination files -- WHY DO WE NEED THIS? implement dfiles param
    dfiles = update_import_destfiles_dict(destination, headers, url_base)

    for finfo in list_agave_dir_files(slisturl, headers):
        fname = finfo['name']

        # if dir and '.': skip if matching, make if missing, ignore if already exists
        if finfo['type'] == 'dir' and fname == '.':
            dirname = basename(finfo['path'])
            if skipdir:
                print(tab+'skipping', dirname, '(matching with {})'.format(basename(destination)))
            else: # mkdir if needed, then update destination and dfiles
                if dirname in dfiles:
                    print(tab+'skipping', dirname, '(exists)')
                else:
                    print(tab+'mkdir', dirname, '(new)')
                    files_mkdir(dirname, destination, headers)
                destination += '/{}'.format(dirname)
                dfiles = update_import_destfiles_dict(destination, headers, url_base)
            tab += '  '

        # elif is not '.' but still directory, recurse
        elif finfo['type'] == 'dir':
            recursion_source = '{}/{}'.format(source,fname)
            recursive_import(recursion_source, destination, headers, url_base, dfiles=dfiles, tab=tab)

        # must be file; import if not in dest dir (new) or source timestamp is newer (modified), otherwise skip
        else:
            fpath = '{}/{}'.format(source, fname)
            if fname not in dfiles:
                print(tab+'importing', fname, '(new)')
                files_import(fpath, destination, headers)
            elif newer_importfile(finfo, dfiles[fname]):
                print(tab+'importing', fname, '(modified)')
                files_import(fpath, destination, headers)
            else:
                print(tab+'skipping', fname, '(exists)')
    return
# end recursive files functions

if __name__ == '__main__':
    
    # arguments
    parser = argparse.ArgumentParser(description='Script to combine files-upload, files-get, and files-import. When recursion (-r) specified, a trailing slash on source path syncs contents of source and destination; no trailing slash nests source under destination.')
    parser.add_argument('-n', '--name', dest='name', help='new file name')
    parser.add_argument('-r', '--recursive', dest='recursive', default=False, action='store_true', help='sync recursively')
    parser.add_argument('source', help='source path (local, agave, or url)')
    parser.add_argument('destination', default='.', nargs='?', help='destination path (local or agave; default $PWD)')
    args = parser.parse_args()

    # if recursive run, ignore name flag
    if args.recursive and args.name is not None:
        print('Ignoring name flag due to recursion.')

    # read cache to get baseurl & token, then build header
    try:
        cache_json = load(open(expanduser(cache)))
        access_token = cache_json['access_token']
        baseurl = cache_json['baseurl']
        expire = datetime.fromtimestamp(int(cache_json['created_at'])+int(cache_json['expires_in']))
    except:
        exit('Error reading from cache {}'.format(cache))
    h = { 'Authorization': 'Bearer {}'.format(access_token) }

    # if access token is expired, quit
    if expire < datetime.now():
        exit('Access token is expired. Please pull valid token and try again.')

    # check for trailing slash on source, then strip slashes
    # if recursing: trailing slash means no nesting
    # else: ERROR because unsure what to do
    source_slash = (args.source[-1] == '/')
    if source_slash and not args.recursive:
        exit('Please provide either a path to a file or specify a recursive response.')
    args.source = (args.source[:-1] if args.source[-1] == '/' else args.source)
    args.destination = (args.destination[:-1] if args.destination[-1] == '/' else args.destination)

    # determine path types
    source_type = get_path_type(args.source)
    dest_type = get_path_type(args.destination)

    # reformat agave urls
    if source_type == agave:
        args.source = agave_path_builder(baseurl, args.source, recursive=args.recursive)
    if dest_type == agave:
        args.destination = agave_path_builder(baseurl, args.destination)

    # source=agave/url and dest=local --> get
    if source_type != local and dest_type == local:
        if not args.recursive: # if no recursion, do simple import
            print('Downloading', basename(args.source), 'to', args.destination, ('as {}'.format(args.name) if args.name is not None else ''))
            files_download(args.source, h, path=args.destination, name=args.name)
        elif source_type == url: # ERROR if recursive and url source
            exit('Cannot recursively download from a generic url. Can only recursively download from an agave system.')
        else: # download recursively from agave source
            print('Beginnning recursive download...')
            recursive_get(args.source, h, baseurl, destination=args.destination, skipdir=source_slash)
    
    # source=local and dest=agave --> upload
    elif source_type == local and dest_type == agave:
        if args.recursive:
            print('Beginning recursive upload...')
            recursive_upload(args.destination, h, baseurl, source=args.source, skipdir=source_slash)
        else:
            print('Uploading', basename(args.source), 'to', args.destination, ('as {}'.format(args.name) if args.name is not None else ''))
            files_upload(expanduser(args.source), args.destination, h, new_name=args.name)

    # source=agave/url and dest=agave --> import
    elif source_type != local and dest_type == agave:
        if not args.recursive: # if no recursion, do simple import
            print('Importing', basename(args.source), 'to', args.destination, ('as {}'.format(args.name) if args.name is not None else ''))
            files_import(args.source, args.destination, h, new_name=args.name)
        elif source_type == url: # ERROR if recursive and url source
            exit('Cannot recursively import from a generic url. Can only recursively import from another agave system.')
        else: # import recursively from agave source
            print('Beginning recursive import...')
            recursive_import(args.source, args.destination, h, baseurl, skipdir=source_slash)

    # other combos --> error 
    else:
        exit('Cannot have source type {} and destination type {}'.format(source_type, dest_type))