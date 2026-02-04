import argparse
import configparser
from datetime import datetime
import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import sys
import zlib

argparser = argparse.ArgumentParser(description="The stupidest content tracker")
argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True

def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)
    match args.command:
        case "add"          : cmd_add(args)
        case "cat-file"     : cmd_cat_file(args)
        case "check-ignore" : cmd_check_ignore(args)
        case "checkout"     : cmd_checkout(args)
        case "commit"       : cmd_commit(args)
        case "hash-object"  : cmd_hash_object(args)
        case "init"         : cmd_init(args)
        case "log"          : cmd_log(args)
        case "ls-files"     : cmd_ls_files(args)
        case "ls-tree"      : cmd_ls_tree(args)
        case "rev-parse"    : cmd_rev_parse(args)
        case "rm"           : cmd_rm(args)
        case "show-ref"     : cmd_show_ref(args)
        case "status"       : cmd_status(args)
        case "tag"          : cmd_tag(args)
        case _              : print("Bad command.")

class GitRepository (object):
    """A git repository"""

    worktree = None #工作区路径
    gitdir = None   #.git文件路径
    conf = None     #配置文件路径

    def __init__(self, path, force=False):                    #force参数用于无地址时强制执行？
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")              #gitdir = path + "/.git"

        if not (force or os.path.isdir(self.gitdir)):         #若文件不存在且非强制执行
            raise Exception(f"Not a Git repository {path}")   #抛出异常：路径并非Git仓库
        
        # Read configuration file in .git/config
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):                         #若cf地址返回成功且真的有这个文件
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file missing")     #抛出异常：配置文件丢失
        
        if not force:                                         #仓库格式版本检查, 寻找"core.repositoryformatversion"对应值是否为0
            vers = int(self.conf.get("core", "repositoryformatversion"))   
            if vers != 0:
                raise Exception("Unsupported repositoryformatversion {vers}")

def repo_path(repo, *path):
    """输入path和repo，输出repo.gitdir + "/path1" + "path2" ..."""
    return os.path.join(repo.gitdir, *path)                      #返回repo.gitdir + "/path"

def repo_file(repo, *path, mkdir=False):                         #返回并可选地创建一个文件的路径。不创建文件，只创建到最后一个目录。
    """输入path和repo，输出repo.gitdir + "/path1" + "path2" ...
    可选项：mkdir，为真时创建指定路径，但不创建文件"""

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)
    
def repo_dir(repo, *path, mkdir=False):                          #返回并可选地创建一个目录的路径。
    """输入path和repo，输出repo.gitdir + "/path1" + "path2" ...
    可选项：mkdir为真时创建对应路径。若对应路径不指向文件夹则报错"""

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if os.path.isdir(path):
            return path
        else:
            raise Exception(f"Not a directory {path}")
        
    if mkdir:
        os.makedirs(path)                                       #创建目录
        return path
    else:
        return None

def repo_create(path):
    """在指定路径生成.git文件，包含branches, objects, refs/tags, refs/heads
    文件夹和description, HEAD, config文件。若指定路径已有.git文件夹或者路径不
    指向一个文件夹而是文件则报错。返回GitRepository对象
    """

    repo = GitRepository(path, True) # force选项为true

    #First, we make sure the path either doesn't exist or is an empty dir.

    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception (f"{path} is not a directory")
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception (f"{path} is not empty")
    else:
        os.makedirs(repo.worktree)

    assert repo_dir(repo, "branches", mkdir=True)
    assert repo_dir(repo, "objects", mkdir=True)
    assert repo_dir(repo, "refs", "tags", mkdir=True)
    assert repo_dir(repo, "refs", "heads", mkdir=True)

    # .git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description' to name the repository.\n")

    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo

def repo_default_config():
    """生成一段配置字符串"""
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

argsp = argsubparsers.add_parser("init", help="Initialize a new, empty repository.")

argsp.add_argument("path",
                   metavar="directory",
                   nargs="?",
                   default=".",
                   help="Where to create the repository.")

def cmd_init(args):
    repo_create(args.path)

def repo_find(path=".", required=True):
    """递归函数。返回一个GiyRepository对象，该对象对应路径在离path最近的.git文件路径。
    path默认值为当前目录。若未查找到.git：required真则返回一个错误，否则返回空。
    """
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, ".git")):   #递归终止条件：当前目录下有.git文件夹
        return GitRepository(path)
    
    # If we haven't returned, recurse in parent
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        # Bottom case
        # path is root.
        if required:
            raise Exception("No git directory.")
        else:
            return None
        
    #Recursive case
    return repo_find(parent, required)

class GitObject (object):

    def __init__(self, data=None):
        if data != None:
            self.deserialize(data)
        else:
            self.init()

    def serialize(self, repo):
        """This function MUST be implemented by subclasses.
        
It must read the object's contents from self.data, a byte string, and
do whatever it takes to convert it into a meaningful representation.
What exactly that means depend on each subclass.
        
        """
        raise Exception("Unimplemented!")
    
    def deserialize(self, repo):
        raise Exception("Unimplemented!")
        
    def init(self):
        pass

def object_read(repo, sha):
    """读取对应哈希值的Objects。返回一个对应类型的Object"""

    path = repo_file(repo, "objects", sha[0:2], sha[2:])

    if not os.path.isfile(path):
        return None
    
    with open (path, "rb") as f:
        raw = zlib.decompress(f.read())

        #Read object type
        x = raw.find(b' ')
        fmt = raw[0:x]

        #Read object size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception(f"Malformed object {sha}: bad length")
        
        # Pick constructor
        match fmt:
            case b'commit' : c=GitCommit
            case b'tree'   : c=GitTree
            case b'tag'    : c=GitTag
            case b'blob'   : c=GitBlob
            case _:
                raise Exception(f"Unknown type {fmt.decode("ascii")} for object {sha}")
            
        #Call constructor and return object
        return c(raw[y+1:]) # 返回一个对应的类型
    
def object_write(obj, repo=None):
    """ 返回obj的sha, 若给出repo路径则生成对应的文件 """
    # Serialize object data
    data = obj.serialize()
    # add header
    result = obj.fmt + b' ' + str(len(data)).encode + b'\x00' + data
    # Compute hash
    sha = hashlib.sha1(result).hexdigest()

    if repo:
        # Compute path
        path=repo_file(repo, "objects", sha[0:2], sha[2:], mkdir=True)

        if not os.path.exists(path):
            with open(path, 'wb') as f:
                f.write(zlib.compress(result))
    return sha

class GitBlob(GitObject):
    fmt = b'blob'

    def serialize(self):
        return self.blobdata
    
    def deserialize(self,data):
        self.blobdata = data

argsp = argsubparsers.add_parser("cat-file",
                                 help="Provide content of repository objects")

argsp.add_argument("type",
                   metavar="type",
                   choices=["blob", "commit", "tag", "tree"],
                   help="Specify the type")

argsp.add_argument("object",
                   metavar="object",
                   help="The object to display")

def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt=args.type.encode())

def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

def object_find(repo, name, fmt=None, follow=True): #名称解析函数，后续继续实现
    """名称解析函数，返回哈希值。"""
    return name

argsp = argsubparsers.add_parser("hash-object",
                                 help="Compute object ID and optionally creates a blob from a file")

argsp.add_argument("-t",
                   metavar="type",
                   dest="type",
                   choices=["blob", "commit", "tag", "tree"],
                   default="blob",
                   help="Specify the type")

argsp.add_argument("-w",
                   dest="write",
                   action="store_true",
                   help="Actually write the object into the database")

argsp.add_argument("path",
                   help="Read object from <file>")

def cmd_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None
    
    with open(args.path, "rb") as fd:
        sha = object_hash(fd, args.type.encode, repo)
        print(sha)

def object_hash(fd, fmt, repo=None):
    """将输入的文件转化为对应类型Object并返回sha。若给出repo则生成对应文件"""
    data = fd.read()

    # Choose constructor according to fmt argument
    match fmt:
        case b'commit' : obj=GitCommit(data)
        case b'tree'   : obj=GitTree(data)
        case b'tag'    : obj=GitTag(data)
        case b'blob'   : obj=GitBlob(data)
        case _: raise Exception(f"Unknown type {fmt}!")

    return object_write(obj, repo)

def kvlm_parse(raw, start=0, dct=None):
    """递归函数，键值列表解析器（用于commit和tag解析。
    raw:传入文件字符串 start:开始解析位置，递归用，默认0. dct:词典
    """

    if not dct:
        dct = dict()
    
    # We search for the next space and the next newline.
    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    # If newlines appears first (or there's no space, in which
    # case find() returns -1), we assume a blank line, which means
    # the remainder of the data is the "message".
    #
    # store it in dct with "None" as the key 
    if (spc < 0) or (nl < spc):
        assert nl == start
        dct[None] = raw[start+1:]
        return dct
    
    # Recursive case

    key = raw[start:spc]

    # Find the end of the value. Continuation lines begin with a
    # space, so we loop until we find a "\n" not followed by a space
    end = start
    while True:
        end = raw.find(b'\n', end+1)
        if raw[end+1] != ord(' '): break

    # drop the leading space on continuation lines
    value = raw[spc+1:end].replace(b'\n', b'\n')

    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [ dct[key], value ]
    else:
        dct[key] = value

    return kvlm_parse(raw, start=end+1, dct=dct)

def kvlm_serialize(kvlm):
    """将kvlm转化为对应文件
    """

    ret = b''

    for k in kvml.keys():
        # Skip the message itself
        if k == None: continue
        val = kvlm[k]

        if type(val) != list:
            val = [ val ]

        for v in val:
            ret += k + b' ' + (v.replace(b'\n',b'\n')) + b'\n'

    ret += b'\n' + kvml[None]

    return ret

class GitCommit(GitObject):
    """fmt='commit'，kvlm为dict，储存键值"""
    fmt=b'commit'

    def deserialize(self, data):
        """将解析后的data放入self.kvml"""
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        """返回文件内容"""
        return kvlm_serialize(self.kvlm)
    
    def init(self):
        self.kvlm = dict()