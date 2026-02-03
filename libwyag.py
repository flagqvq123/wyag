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
    """Compute path under repo's gitdir"""
    return os.path.join(repo.gitdir, *path)                      #返回repo.gitdir + "/path"

def repo_file(repo, *path, mkdir=False):                         #返回并可选地创建一个文件的路径。不创建文件，只创建到最后一个目录。
    """Same as repo_path, but create dirname(*path) if absent. For
    example, repo_file(r, \"refs\", \"heads\", \"master\") will create
    .git/refs/heads if it doesn't exist."""

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)
    
def repo_dir(repo, *path, mkdir=False):                          #返回并可选地创建一个目录的路径。
    """Same as repo_path, but mkdir *path if absent if mkdir."""

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
    """Create a new repository at path"""

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