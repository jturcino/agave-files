#!/usr/bin/env python

import argparse
from os.path import expanduser, isfile, isdir, basename, dirname, getmtime
from json import load, loads, dumps
from requests import get, post
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

# request wrappers
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
    files = {'fileToUpload': (new_name, open(localfile, 'rb'))}
    r = post(url, headers=headers, files=files)
    assert r.status_code == 202, 'Command status code is {}, not 202'.format(r.status_code)
    return
# end request wrappers

def list_agave_dir_files(url, headers):
    '''Performs files-list on remote agave directory and returns list of file JSON descriptions'''
    r = get(url, headers=headers)
    assert r.status_code == 200, 'Unable to list files at {}; status code {}'.format(url, r.status_code)
    l = loads(r.content)
    assert l.get('result') is not None, 'Unable to read file info from key "result" in JSON \n{}'.format(dumps(l, indent=2))
    return l['result']

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

def newer_agavefile(localfile, agave_description):
    '''Given local filepath and Agave file JSON description (only lastModified key required), return TRUE if Agave file is more recently modified.'''
    assert isfile(localfile) or isdir(localfile), 'Local file {} does not exist'.format(localfile)
    assert 'lastModified' in agave_description, 'lastModified key not in Agave description keys: {}'.format(agave_description.keys())
    local_modtime = get_localfile_modtime(localfile)
    agave_modtime = get_agavefile_modtime(agave_description)
    return (agave_modtime > local_modtime)
# end modification time helper functions

def recursive_get(url, headers, destination='.', url_type=url, url_base=None, tab=''):
    '''Performs recursive files-get from remote to local location'''
    # if agave get listable url
    if url_type == agave:
        url = agave_path_setlisting(url, url_base, listings=True)

    # perform files-list on path
    list_json = list_agave_dir_files(url, headers)
    for i in list_json:
        filename = i['name']

        # is directory
        if i['type'] == 'dir':
            # if base ('.'), add name to dest and make local dir if DNE
            if filename == '.':
                directoryname = basename(i['path'])
                destination += '/{}'.format(directoryname)
                if not isdir(destination):
                    print(tab+'mkdir', destination)
                    makedirs(destination)
                else:
                    print(tab+'skipping', directoryname, '(exists)')
                tab += '  '

            # else, add dir to url and recurse
            else:
                recursion_url = '{}/{}'.format(url,filename)
                recursive_get(recursion_url, headers, destination=destination, url_type=url_type, tab=tab)

        # is file
        else:
            # build file url by adding filename; if agave type, replace 'listings' with 'media' in base path
            file_url = '{}/{}'.format(url, filename)
            # TODO: fix this...use agave_path_setlisting somehow
            if url_type == agave:
                file_url = file_url.replace('listings', 'media', 1)

            # if remote file not at local destination, download
            if filename not in listdir(destination):
                print(tab+'downloading', filename, '(new)')
                files_download(file_url, headers, path=destination)

            # elif remote file edited more recently than local file, download
            else:
                filename_fullpath = '{}/{}'.format(destination, filename)
                if newer_agavefile(filename_fullpath, i):
                    print(tab+'downloading', filename, '(modified)')
                    files_download(file_url, headers, path=destination)
                else:
                    print(tab+'skipping', filename, '(exists)')
    return

def recursive_upload(url, headers, source='.', url_type=url, url_base=None, tab=''):
    '''Recursively upload files from a local directory to an agave directory'''

    # if agave url, make listable
    if url_type == agave:
        url = agave_path_setlisting(url, url_base, listings=True)

    # check url EXISTS and is type DIR
    # make dir of urlfiles info { name:{modified, tyep}}
    urlfiles = list_agave_dir_files(url, headers)
    urlinfo = {i['name']:{'lastModified':i['lastModified'],'type':i['type']} for i in urlfiles}
    assert '.' in urlinfo, 'Url {} is not valid directory'.format(url)

    for filename in listdir(expanduser(source)):
        fullpath = '{}/{}'.format(expanduser(source), filename)
        # if is FIle and present at source, dest
        # then check modification dates; upload if local is newer
        if isfile(fullpath) and filename in urlinfo:
            if newer_agavefile(fullpath, urlinfo[filename]):
                print(tab+'skipping', filename, '(exists)')
            else:
                print(tab+'uploading', filename, '(modified)')



        # get type (file, dir)
        # if has name,type match in urlfiles and is FILE: (no need to do anything if is dir)
            # check modified dates
            # upload sourcefile if newer
        # else:
            # if file:
                # upload it
            # else is dir:
                # make it

        # if dir:
            # add name to url, source
            # recurse
    return

if __name__ == '__main__':
    
    # arguments
    parser = argparse.ArgumentParser(description="Script to combine file-upload, files-get, and files-import. RSYNC FORMATTING NOT YET IMPLEMENTED; CURRENTLY USING FLAGS, NOT POSITIONAL ARGS.")
    parser.add_argument('-s', '--source', dest='source', required=True, help='source file path (local, agave system, or url)')
    parser.add_argument('-d', '--destination', dest='dest', default='.', help='destination file path (local or agave system; defaults to $PWD)')
    parser.add_argument('-f', '--new-name', dest='new_name', help='new file name')
    parser.add_argument('-r', '--recursive', dest='recursive', action='store_true', help='act on souce path recursively')
    args = parser.parse_args()

    # read cache to get token & baseurl, then build header
    try:
        cache_json = load(open(expanduser(cache)))
        access_token = cache_json['access_token']
        baseurl = cache_json['baseurl']
    except:
        exit('Error reading access token and baseurl from cache {}'.format(cache))
    h = { 'Authorization': 'Bearer {}'.format(access_token) }

    # determine source and destination path types
    # reformat agave urls with baseurl
    source_type = get_path_type(args.source)
    if source_type == agave:
        args.source = agave_path_builder(baseurl, args.source, recursive=args.recursive)
    dest_type = get_path_type(args.dest)
    if dest_type == agave:
        args.dest = agave_path_builder(baseurl, args.dest)

    # source=agave/url and dest=local --> get
    if source_type != local and dest_type == local:
        if args.recursive:
            print('BEGINNING RECURSIVE GET')
            recursive_get(args.source, h, destination=args.dest, url_type=source_type, url_base=baseurl)
        else:
            files_download(args.source, h, path=args.dest, name=args.new_name)
    
    # source=local and dest=agave --> upload
    elif source_type == local and dest_type == agave:
        files_upload(expanduser(args.source), args.dest, h, new_name=args.new_name)
        print(dumps(data, indent=2))

    # source=agave/url and dest=agave --> import
    elif source_type != local and dest_type == agave:
        payload = {'urlToIngest': args.source, 'fileName': args.new_name}
        cmd = post(args.dest, headers=h, data=payload)
        assert cmd.status_code == 202, 'Failed files-get, returned code {}'.format(str(cmd.status_code))
        data = loads(cmd.text)
        print(dumps(data, indent=2))

    # other combos --> error 
    else:
        exit('Cannot have source type {} and destination type {}'.format(source_type, dest_type))