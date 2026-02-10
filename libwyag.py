import argparse
import configparser
from datetime import datetime
import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import re
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
    """ 返回obj的sha, 若提供repo则生成对应的文件 """
    # 调用serialize()函数获得该对象序列化数据
    data = obj.serialize()
    # 加头
    result = obj.fmt + b' ' + str(len(data)).encode + b'\x00' + data
    # 计算哈希值
    sha = hashlib.sha1(result).hexdigest()

    if repo:
        # 计算路径
        path=repo_file(repo, "objects", sha[0:2], sha[2:], mkdir=True)
        # 不存在时写入
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

def object_find(repo, name, fmt=None, follow=True):
    """名称解析函数，返回哈希值。
    repo -> 仓库对象
    name -> 对象名称,支持hash, short hash, tag, branch, HEAD
    fmt -> 期望的对象类型,函数会确保返回的对象是特定类型
    follow -> 是否跟随tag和commit指向的对象继续解析
    """
    sha = object_resolve(repo, name)

    if not sha:
        raise Exception(f"No such reference {name}")
    
    if len(sha) > 1:
        raise Exception("Ambiguous reference {name}: Candidates are: \n - {'\n - '.join(sha)}.")
    
    sha = sha[0]

    if not fmt:
        return sha
    
    while True:
        obj = object_read(repo, sha)

        if obj.fmt == fmt:
            return sha
        if not follow:
            return None
        
        if obj.fmt == b'tag':
            sha = obj.kvlm[b'object'].decode("ascii")
        elif obj.fmt == b'commit' and fmt == b'tree':
            sha = obj.kvlm[b'tree'].decode("ascii")
        else:
            return None

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

    for k in kvlm.keys():
        # Skip the message itself
        if k == None: continue
        val = kvlm[k]

        if type(val) != list:
            val = [ val ]

        for v in val:
            ret += k + b' ' + (v.replace(b'\n',b'\n')) + b'\n'

    ret += b'\n' + kvlm[None]

    return ret

class GitCommit(GitObject):
    """由键值对kvlm组成, 包含Tree -> 当次提交对应Tree对象,
    parent -> 父节点, 数量不定。author -> 提交作者
    gpgsig -> 该次提交对象的PGP签名 None -> 提交信息message
    fmt='commit', kvlm为dict, 储存键值"""
    fmt=b'commit'

    def deserialize(self, data):
        """将解析后的data放入self.kvml"""
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        """返回文件内容"""
        return kvlm_serialize(self.kvlm)
    
    def init(self):
        self.kvlm = dict()

argsp = argsubparsers.add_parser("log", help="Display history of a given commit")
argsp.add_argument("commit",
                   default="HEAD",
                   nargs="?",
                   help="Commit to start at.")

def cmd_log(args):
    repo = repo_find()

    print("digraph wyaglog{")
    print("  node[shape=rect]")
    log_graphviz(repo, object_find(repo, args.commit), set())

def log_graphviz(repo, sha, seen):
    """递归函数。graphviz实现逻辑，不需要掌握"""

    if sha in seen:
        return
    seen.add(sha)

    commit = object_read(repo, sha)
    message = commit.kvlm[None].decode("utf8").strip()
    message = message.replace("\\","\\\\")
    message = message.replace("\"","\\\"")

    if "\n" in message:
        message = message[:message.index("\n")]

    print(f"  c_{sha} [lable=\"{sha[0:7]}: {message}\"]")
    assert commit.fmt == b'commit'

    if not b'parent' in commit.kvlm.keys():
        return
    
    if type(parents) != list:
        parents = [ parents ]

    for p in parents:
        p = p.decode("ascii")
        print (f"  c_{sha} -> c_{p};")
        log_graphviz(repo, p, seen)

class GitTreeLeaf (object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha

def tree_paser_one(raw, start=0):
    """读取单个文件并转换为TreeLeaf类型。输入：字符串raw，开始位start。
    输出：结束位，一个对应的树叶，sha"""
    # Find the space terminator of the mode
    x = raw.find(b' ', start)
    assert x-start == 5 or x-start == 6

    # Read the mode
    mode = raw[start:x]
    if len(mode) == 5:
        # Normalize to six bytes.
        mode = b"0" + mode
    
    # Find the NULL terminator of the path
    y = raw.find(b'.\x00', x)
    # and read the path
    path = raw[x+1:y]

    # Read the SHA
    raw_sha = int.from_bytes(raw[y+1:y+21], "big")
    # and convert it into an hex string, padded to 40 chars
    # with zero if needed.
    sha = format(raw_sha, "040x")
    return y+21, GitTreeLeaf(mode, path.decode("utf8"), sha)

def tree_prase(raw):
    """将Tree文件解析为一组树叶。输入字符串，输出一个树叶列表"""
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_paser_one(raw, pos)
        ret.append(data)

    return ret

def tree_leaf_sort_key(leaf):
    """Tree序列化的排序函数，决定items中树叶顺序，以path进行排序"""
    if leaf.mode.startswith(b"10"):
        return leaf.path
    else:
        return leaf.path + "/"
    
def tree_serialize(obj):
    """Tree的序列化函数（文件化）。输入树对象，输出序列化的字符串"""
    obj.items.sort(key=tree_leaf_sort_key)
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path.encode("utf8")
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret

class GitTree(GitObject):
    """内含一个items列表，储存所有树叶"""
    fmt=b'tree'

    def deserialize(self, data):
        self.items = tree_prase(data)

    def serialize(self):
        return tree_serialize(self)
    
    def init(self):
        self.items = list()

argsp = argsubparsers.add_parser("ls-tree", help="Pretty print a tree obj.")
argsp.add_argument("-r",
                   dest="recursive",
                   action="store_true",
                   help="Recurse into sub-trees")

argsp.add_argument("tree",
                   help="A tree-ish object")

def cmd_ls_tree(args):
    repo = repo_find()
    ls_tree(repo, args.tree, args.recursive)

def ls_tree(repo, ref, recursive=None, prefix=""):
    """展示树Tree对象的所有树叶。若recursive选项为真时，递归展示所有树叶。
    ref -> 指定Tree名字"""
    sha = object_find(repo, ref, fmt=b"tree")
    obj = object_read(repo, sha)
    for item in obj.items:
        if len(item.mode) == 5:
            type = item.mode[0:1]
        else:
            type = item.mode[0:2]
        
        match type:
            case b'04': type = "tree"
            case b'10': type = "blob" # A regular file
            case b'12': type = "blob" # A symlink. Blob contents is link target.
            case b'16': type = "commit"
            case _: raise Exception(f"Weird tree leaf mode {item.mode}")
        
        if not (recursive and type == 'tree'): # This is a leaf
            print(f"{'0' * (6-len(item.mode)) + item.mode.decode("ascii")} {type} {item.sha}\t{os.path.join(prefix, item.path)}")
        else: # This is a branch, recurse
            ls_tree(repo, item.sha, recursive,os.path.join(prefix, item.path))

argsp = argsubparsers.add_parser("checkout", help="Checkout a commit inside of a directory")

argsp.add_argument("commit",
                   help="The commit or tree to checkout")

argsp.add_argument("path",
                   help="The EMPTY directory to checkout on.")

def cmd_checkout(args):
    """checkout命令的bridgh函数, 进行操作前的检查和报错"""
    repo = repo_find()

    sha = object_find(repo, args.commit)
    obj = object_read(repo, sha)

    # 将commit中的tree作为obj
    if obj.fmt == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))

    # 检查path状态：不存在则生成; 存在且非空则报错; 存在且非文件夹则报错
    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception(f"Not a directory {args.path}!")
        if os.listdir(args.path):
            raise Exception(f"Not empty {args.path}!")
    else:
        os.makedirs(args.path)

    tree_checkout(repo, obj, os.path.realpath(args.path))

def tree_checkout(repo, tree, path):
    """递归生成一棵树在指定path"""
    for item in tree.items:
        obj = object_read(repo, item.sha)
        dest = os.path.join(path, item.path)

        if obj.fmt == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.fmt == b'blob':
            with open(dest, 'wb') as f:
                f.write(obj.blobdata)

def ref_resolve(repo, ref):
    """指针解析器, 输入一个指针文件的地址, 返回指针指向的最终对象的哈希值。"""
    path = repo_file(repo, ref)

    # 在init后, Head -> main -> None, 此时不存在任何可指向的提交
    if not os.path.isfile(path):
        return None
    
    with open(path, 'r') as fp:
        data = fp.read[:-1]
        # Drop final \n
    if data.startswith("ref: "):  
        ref_resolve(repo, data[5:])
    else:
        return data

def ref_list(repo, path=None):
    """输出指定路径(默认.git/refs)中所有文件指向对象哈希值的字典。
    文件夹则对应其内部文件组成的字典"""
    if not path:
        path = repo_dir(repo, "refs")
    ret = dict()
    # 按照Git的要求, 依照顺序输出字典
    for f in sorted(os.listdir(path)):
        can = os.path.join(path, f)
        if os.path.isdir(can):
            ret[f] = ref_list(repo, can)
        else:
            ret[f] = ref_resolve(repo, can)

    return ret

argsp = argsubparsers.add_parser("show-ref", help="List reference.")

def cmd_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix="refs")

def show_ref(repo, refs, with_hash=True, prefix=""):
    """递归函数, 打印refs中所有的指针
    refs -> 字典, 来自于 ref_list(repo, path)
    with_hash -> 是否在打印时附带指针指向对象的哈希值
    prefix -> 递归用, 记录前面递归的路径"""
    if prefix:
        prefix = prefix + '/'
    
    for k, v in refs.items():
        if type(v) == str and with_hash:
            print (f"{v} {prefix}{k}")
        elif type(v) == str:
            print (f"{prefix}{k}")
        else:
            show_ref(repo, v, with_hash=with_hash, prefix=f"{prefix}{k}")

class GitTag(GitCommit):
    fmt = b'tag'

argsp = argsubparsers.add_parser("tag", help="List and create tags")

argsp.add_argument("-a",
                   action="store_true",
                   dest="create_tag_object",
                   help="")

argsp.add_argument("name",
                   nargs="?",
                   help="The new tag's name")

argsp.add_argument("object",
                   default="HEAD",
                   nargs="?",
                   help="The object the new tag will point to")

def cmd_tag(args):
    repo = repo.find()

    if args.name:
        tag_create(repo,
                   args.name,
                   args.object,
                   create_tag_object = args.create_tag_object)
    else:
        refs = ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)

def tag_create(repo, name, ref, create_tag_object=False):
    sha = object_find(repo, ref)

    if create_tag_object:
        # 创建一个tag对象（标记commit）
        tag = GitTag()
        tag.kvlm = dict()
        tag.kvlm[b'object'] = sha.encode()
        tag.kvlm[b'type'] = b'commit'
        tag.kvlm[b'tag'] = name.encode()
        tag.kvlm[b'tagger'] = b'Wyag <wyag@example.com>'

        tag.kvlm[None] = b"A tag generated by wyag, which won't let you customize the message!\n"
        tag_sha = object_write(tag, repo)
        ref_create(repo, "tags/" + name, tag_sha)

def ref_create(repo, ref_name, sha):
    with open(repo_file(repo, "refs/" + ref_name), 'w') as fp:
        fp.write(sha + '\n')

def object_resolve(repo, name):
    """"将一个对象的名称解析为hash值返回。
    支持的输入：
        - hash
        - short hash(有模糊歧义)
        - tags(有模糊歧义)
        - branches(有模糊歧义)
        - HEAD"""
    
    candidates = list()
    hashRE = re.compile(r"^[0-9A-Fa-f]{4,40}$")

    # 空名字忽略
    if not name.strip():
        return None
    
    # HEAD
    if name == "HEAD":
        return [ ref_resolve(repo, "HEAD") ]
    
    # 十六进制字符串则尝试hash解析
    if hashRE.match(name):
        # Git应该需要至少四位来分辨hash
        name = name.lower()
        prefix = name[0:2]
        path = repo_dir(repo, "objects", prefix, mkdir=False)
        if path:
            rem = name[2:]
            for f in os.listdir(path):
                if f.startswith(rem):
                    candidates.append(prefix + f)

    # 尝试寻找指针
    as_tag = ref_resolve(repo, "refs/tags/" + name)
    if as_tag:
        candidates.append(as_tag)

    as_branch = ref_resolve(repo, "refs/heads/" + name)
    if as_branch:
        candidates.append(as_branch)

    as_remote_branch = ref_resolve(repo, "refs/remotes/" + name)
    if as_remote_branch:
        candidates.append(as_remote_branch)

    return candidates

argsp = argsubparsers.add_parser("rev-parse",
                                 help="Parse revision (or other objects) identifiers")

argsp.add_argument("--wyag-type",
                   metavar="type",
                   dest="type",
                   choices=["blob", "commit", "tag", "tree"],
                   default=None,
                   help="Specify the expected type")

argsp.add_argument("name",
                   help="The name to parse")

def cmd_rev_parse(args):
    """
    rev-parse命令的bridge函数, 进行参数处理
    返回输入目标的哈希值
    """
    if args.type:
        fmt = args.type.encode()
    else:
        fmt = None
    
    repo = repo_find()

    print (object_find(repo, args.name, fmt, follow=True))

class GitIndexEntry (object):
    """索引“条目”, 每个表示一个文件"""
    def __init__(self, ctime=None, mtime=None, dev=None, ino=None,
                 mode_type=None, mode_perms=None, uid=None, gid=None,
                 fsize=None, sha=None, flag_assume_valid=None,
                 flag_stage=None, name=None):
        # 上一次文件元数据变化时间
        self.ctime = ctime
        # 上一次文件数据改变时间
        self.mtime = mtime
        # 包含此文件的设备的 ID
        self.dev = dev
        # 文件的索引数
        self.ino = ino
        # 对象类型, b1000(regular), b1010(symlink), b1110(gitlink)
        self.mode_type = mode_type
        # 对象权限，整数
        self.mode_perms = mode_perms
        # 使用者 ID
        self.uid = uid
        # 组织 ID
        self.gid = gid
        # 对象大小, 字节数
        self.fsize = fsize
        # 对象 SHA
        self.sha = sha
        self.flag_assume_valid = flag_assume_valid
        self.flag_stage = flag_stage
        # 对象的名字(完整名)
        self.name = name

class GitIndex (object):
    version = None
    entries = []
    # ext = None
    # sha = None

    def __init__(self, version=2, entries=None):
        if not entries:
            entries = list()

            self.version = version
            self.entries = entries

def index_read(repo):
    """index文件解析器, 读取.git/index文件并返回一个GitIndex类"""
    index_file = repo_file(repo, "index")

    # 新目录下无index存在
    if not os.path.exists(index_file):
        return GitIndex
    
    with open(index_file, 'rb') as f:
        raw = f.read()

    header = raw[:12]
    signature = header[:4]
    assert signature == b'DIRC' # 意思是'DirCache'
    version = int.from_bytes(header[4:8], "big")
    assert version == 2, "wyag only supports index file version 2"
    count = int.from_bytes(header[8:12], "big")

    entries = list()

    content = raw[12:]
    idx = 0
    for i in range(0,count):
        # Read creation time, as a unix timestamp (seconds since
        # 1970-01-01 00:00:00, the epoch)
        ctime_s = int.from_bytes(content[idx: idx+4], "big")
        # Read creation time, as nanoseconds after that timestamps,
        # for extra precision.
        ctime_ns = int.from_bytes(content[idx+4: idx+8], "big")
        # Same for modification time: first seconds from epoch.
        mtime_s = int.from_bytes(content[idx+8: idx+12], "big")
        mtime_ns = int.from_bytes(content[idx+12: idx+16], "big")
        # Device ID
        dev = int.from_bytes(content[idx+16: idx+20], "big")
        # Inode
        ino = int.from_bytes(content[idx+20: idx+24], "big")
        # Ignored.
        unused = int.from_bytes(content[idx+24: idx+26], "big")
        assert 0 == unused
        mode = int.from_bytes(content[idx+26: idx+28], "big")
        mode_type = mode >> 12
        assert mode_type in [0b1000, 0b1010, 0b1110]
        mode_perms = mode & 0b0000000111111111
        # User ID
        uid = int.from_bytes(content[idx+28: idx+32], "big")
        # Group ID
        gid = int.from_bytes(content[idx+32: idx+36], "big")
        # Size
        fsize = int.from_bytes(content[idx+36: idx+40], "big")
        # SHA (obj ID). We'll store it as a lowercase hex string
        # for consistency
        sha = format(int.from_bytes(content[idx+36:idx+40], "big"), "040x")
        # Flags (we are going to ignore)
        flags = int.from_bytes(content[idx+60: idx+62], "big")
        # Parse flags
        flag_assume_valid = (flags & 0b1000000000000000) != 0
        flag_extended = (flags & 0b0100000000000000) != 0
        assert not flag_extended
        flag_stage =  flags & 0b0011000000000000
        # Length of the name.  This is stored on 12 bits, some max
        # value is 0xFFF, 4095.  Since names can occasionally go
        # beyond that length, git treats 0xFFF as meaning at least
        # 0xFFF, and looks for the final 0x00 to find the end of the
        # name --- at a small, and probably very rare, performance
        # cost.
        name_length = flags & 0b0000111111111111

        # We've read 62 bytes so far.
        idx += 62

        if name_length < 0xFFF:
            assert content[idx + name_length] == 0x00
            raw_name = content[idx:idx+name_length]
            idx += name_length + 1
        else:
            print(f"Notice: Name is 0x{name_length:X} bytes long.")
            null_idx = content.find(b'\x00', idx + 0xFFF)
            raw_name = content[idx: null_idx]
            idx = null_idx + 1
        
        name = raw_name.decode("utf8")

        idx = 8 * ceil(idx / 8)

        entries.append(GitIndexEntry(ctime=(ctime_s, ctime_ns),
                                     mtime=(mtime_s, mtime_ns),
                                     dev=dev,
                                     ino=ino,
                                     mode_type=mode_type,
                                     mode_perms=mode_perms,
                                     uid=uid,
                                     gid=gid,
                                     fsize=fsize,
                                     sha=sha,
                                     flag_assume_valid=flag_assume_valid,
                                     flag_stage=flag_stage,
                                     name=name))
        
    return GitIndex(version=version, entries=entries)

argsp = argsubparsers.add_parser("ls-files", help="List all the stage files")
argsp.add_argument("--verbose", action="store_true", help="Show everything")

def cmd_ls_files(args):
    repo = repo_find()
    index = index_read(repo)
    if args.verbose:
        print(f"Index dile format v{index.version}, containing {len(index.entries)} entries.")

    for e in index.entries:
        print(e.name)
        if args.verbose:
            entry_type = {0b1000: "regular file",
                          0b1010: "symlink",
                          0b1110: "git link"}[e.mode_type]
            print(f"  {entry_type} with perms: {e.mode_perms:o}")
            print(f"  on blob: {e.sha}")
            print(f"  created: {datetime.fromtimestamp(e.ctime[0])}.{e.ctime[1]}, modified: {datetime.fromtimestamp(e.mtime[0])}.{e.mtime[1]}")
            print(f"  device: {e.dev}, inode: {e.ino}")
            print(f"  user:{pwd.getpwuid(e.uid).pw_name} ({e.uid})  group: {grp.getgrnam(e.gid).gr_name} ({e.gid})")
            print(f"  flags: stage={e.flag_stage}  assume_valid={e.flag_assume_valid}")

