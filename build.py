#!/usr/bin/env python3
import errno
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from argparse import ArgumentParser

import base64
import os
import shutil

import file_expander

transcrypt_arguments = ['-n', '-p', '.none']
transcrypt_dirty_args = transcrypt_arguments + []
transcrypt_clean_args = transcrypt_arguments + ['-b']

rollup_arguments = ['--format', 'cjs']


def possible_transcrypt_binary_paths(config):
    """
    Finds all different places to look for a `transcrypt` binary to run.

    :type config: Configuration
    """
    return [
        os.path.join(config.base_dir, 'env', 'bin', 'transcrypt'),
        os.path.join(config.base_dir, 'env', 'Scripts', 'transcrypt.exe'),
        shutil.which('transcrypt'),
        shutil.which('transcrypt.exe'),
    ]


def possible_rollup_binary_paths(config):
    """
    Finds all different places to look for a `rollup` binary to run.

    :type config: Configuration
    """
    return [['npx', 'rollup']]
    npm = config.find_misc_executable('npm')
    if npm is None:
        raise Exception("npm not found! tried paths: {}".format(possible_rollup_binary_paths(config)))

    args = [npm, 'bin']
    ran_npm = subprocess.run(args, capture_output=True, encoding='utf-8')

    if ran_npm.returncode != 0:
        raise Exception("npm bin failed. exit code: {}. command line '{}'. stderr: {}. stdout: {}"
                        .format(ran_npm.returncode, "' '".join(args), ran_npm.stderr, ran_npm.stdout))
    npm_bin_dir = ran_npm.stdout.strip()
    # if we're running on Windows, then we need to explicitly use rollup.cmd or rollup.ps1 rather than rollup - rollup will still exist, it will just be an unexecutable shell file ._.
    if os.name == 'nt':
        return [
            os.path.join(npm_bin_dir, 'rollup.cmd'),
            os.path.join(npm_bin_dir, 'rollup.ps1'),
            os.path.join(npm_bin_dir, 'rollup'),
        ]
    else:
        return [
            os.path.join(npm_bin_dir, 'rollup'),
        ]


def possible_pip_binary_paths(config):
    """
    Finds all different places to look for a `pip` binary to run.

    :type config: Configuration
    """
    files = [
        os.path.join(config.base_dir, 'env', 'bin', 'pip'),
        os.path.join(config.base_dir, 'env', 'bin', 'pip.exe'),
        os.path.join(config.base_dir, 'env', 'Scripts', 'pip.exe')
    ]
    if not config.enter_env:
        for path in [shutil.which('pip'), shutil.which('pip.exe')]:
            if path is not None:
                files.append(path)

    return files


class Configuration:
    """
    Utility struct holding all configuration values.

    :type base_dir: str
    :type username: str
    :type password: str
    :type branch: str
    :type ptr: bool
    """

    def __init__(self, base_dir, config_json:dict, clean_build=True, flatten=False):
        """
        :type base_dir: str
        :type config_json: dict[str, str | bool]
        """
        self.base_dir = base_dir
        self.token = config_json.get('token')
        self.username = config_json.get('username') or config_json.get('email')
        self.password = config_json.get('password')
        self.branch = config_json.get('branch', 'default')
        self.url = config_json.get('url', 'https://screeps.com')
        self.ptr = config_json.get('ptr', False)
        self.enter_env = config_json.get('enter-env', True)

        self.clean_build = clean_build
        self.flatten = flatten

    def transcrypt_executable(self):
        """
        Utility method to find a transcrypt executable file.

        :rtype: str
        """
        for path in possible_transcrypt_binary_paths(self):
            if path is not None and os.path.exists(path):
                return path
        return None

    def pip_executable(self):
        """
        Utility method to find a pip executable file.

        :rtype: str
        """
        for path in possible_pip_binary_paths(self):
            if path is not None and os.path.exists(path):
                return path
        return None

    def find_misc_executable(self, file_base):
        """
        Utility method to find a misc. executable file. Tries the basename and basename + '.exe' for Windows.

        :type file_base: str
        :rtype: str
        """
        possible_paths = [
            shutil.which(file_base),
            shutil.which(file_base + '.exe'),
        ]
        for path in possible_paths:
            if path is not None and os.path.exists(path):
                return path
        return None

    def rollup_executable(self):
        """
        Utility method to find a rollup executable file.

        :rtype: str
        """
        for path in possible_rollup_binary_paths(self):
            return path
            if path is not None and os.path.exists(path):
                return path
        return None

    @property
    def source_dir(self):
        """:rtype: str"""
        if self.flatten:
            return os.path.join(self.base_dir, 'src', '__py_build__')
        else:
            return os.path.join(self.base_dir, 'src')


def load_config(base_dir):
    """
    Loads the configuration from the `config.json` file.

    :type base_dir: str
    :rtype: Configuration
    """
    parser = ArgumentParser()
    parser.add_argument("-c", "--config-file", type=str, default='config.json',
                        help="file to load configuration from")
    parser.add_argument("-d", "--dirty-build", action='store_true',
                        help="if true, use past built files for files who haven't changed")
    parser.add_argument("-e", "--expand-files", action='store_true',
                        help="""Alternative to Transcrypt's -xpath option for \
                        finding nested modules.  Use this option if Transcrypt \
                        is unable to import nested .py files""")
    args = parser.parse_args()

    config_file = os.path.join(base_dir, 'config.json')

    with open(os.path.join(base_dir, config_file)) as f:
        config_json = json.load(f)

    return Configuration(base_dir, config_json, clean_build=not args.dirty_build, flatten=args.expand_files)


def run_transcrypt(config):
    """
    Compiles source code using the `transcrypt` program.

    :type config: Configuration
    """
    transcrypt_executable = config.transcrypt_executable()
    if transcrypt_executable is None:
        raise Exception("transcrypt not found! tried paths: {}".format(possible_transcrypt_binary_paths(config)))

    source_main = os.path.join(config.source_dir, 'main.py')

    if config.clean_build:
        cmd_args = transcrypt_clean_args
    else:
        cmd_args = transcrypt_dirty_args

    args = [transcrypt_executable] + cmd_args + [source_main]

    ret = subprocess.Popen(args, cwd=config.source_dir).wait()

    if ret != 0:
        raise Exception("transcrypt failed. exit code: {}. command line '{}'. working dir: '{}'."
                        .format(ret, "' '".join(args), config.source_dir))


def copy_artifacts(config):
    """
    Copies compiled JavaScript files to output directory after `transcrypt` has been run.

    :type config: Configuration
    """
    dist_directory = os.path.join(config.base_dir, 'dist')

    try:
        os.makedirs(dist_directory)
    except OSError as e:
        if e.errno == errno.EEXIST:
            shutil.rmtree(dist_directory)
            os.makedirs(dist_directory)
        else:
            raise

    # rollup_executable = config.rollup_executable()
    rollup_executable = ['npx', 'rollup']
    # node_js = config.find_misc_executable('node')
    if rollup_executable is None:
        raise Exception("rollup not found! tried paths: {}.\nDid you \
        remember to `npm install`?".format(possible_rollup_binary_paths(config)))
    transcrypt_generated_main = os.path.join(config.source_dir, '__target__', 'main.js')
    args = rollup_executable + rollup_arguments + ['--input', transcrypt_generated_main]

    result = subprocess.run(args, cwd=config.source_dir, capture_output=True)
    print(result.stderr.decode('utf-8'), file=sys.stderr)

    if result.returncode != 0:
        raise Exception("rollup failed. exit code: {}. command line '{}'. working dir: '{}'."
                        .format(result.returncode, "' '".join(args), config.source_dir))

    with open(os.path.join(dist_directory, 'main.js'), 'wb') as f:
        f.write(result.stdout)

    js_directory = os.path.join(config.base_dir, 'js_files')

    if os.path.exists(js_directory) and os.path.isdir(js_directory):
        for name in os.listdir(js_directory):
            source = os.path.join(js_directory, name)
            dest = os.path.join(dist_directory, name)
            shutil.copy2(source, dest)


def build(config):
    """
    Compiles source code, and copies JavaScript files to output directory.

    :type config: Configuration
    """
    print("running transcrypt...")
    run_transcrypt(config)
    print("copying artifacts...")
    copy_artifacts(config)
    print("build successful.")


def upload(config):
    """
    Uploads JavaScript files found in the output directory to the Screeps server.

    :type config: Configuration
    """

    module_files = {}

    dist_dir = os.path.join(config.base_dir, 'dist')

    for file_name in os.listdir(dist_dir):
        # there will be an error if there's non latin alphabet in the files when encoding is not set to utf8
        with open(os.path.join(dist_dir, file_name), encoding='utf8') as f:
            module_files[os.path.splitext(file_name)[0]] = f.read()

    if config.ptr:
        post_url = '{}/ptr/api/user/code'.format(config.url)
    else:
        post_url = '{}/api/user/code'.format(config.url)

    post_data = json.dumps({'modules': module_files, 'branch': config.branch}).encode('utf-8')

    # headers = {'Content-Type': b'application/json; charset=utf-8'}
    # if config.token:
    #     headers['X-Token'] = config.token.encode('utf-8')
    # else:
    #     auth_pair = config.username.encode('utf-8') + b':' + config.password.encode('utf-8')
    #     headers['Authorization'] = b'Basic ' + base64.b64encode(auth_pair)
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    if config.token:
        headers['X-Token'] = config.token
    else:
        auth_pair = config.username + ':' + config.password
        headers['Authorization'] = 'Basic ' + base64.b64encode(auth_pair).decode()

    request = urllib.request.Request(post_url, post_data, headers)
    if config.url != 'https://screeps.com':
        print("uploading files to {}, branch {}{}..."
              .format(config.url, config.branch, " on PTR" if config.ptr else ""))
    else:
        print("uploading files to branch {}{}...".format(config.branch, " on PTR" if config.ptr else ""))

    # any errors will be thrown.
    with urllib.request.urlopen(request) as response:
        decoded_data = response.read().decode('utf-8')
        json_response = json.loads(decoded_data)
        if not json_response.get('ok'):
            if 'error' in json_response:
                raise Exception("upload error: {}".format(json_response['error']))
            else:
                raise Exception("upload error: {}".format(json_response))

    print("upload successful.")


def install_env(config):
    """
    Creates a venv environment in the `env/` folder, and attempts to install `transcrypt` into it.

    If `enter-env` is False in the `config.json` file, this will instead install `transcrypt`
    into the default location for the `pip` binary which is in the path.

    :type config: Configuration
    """
    if config.transcrypt_executable() is not None:
        return
    if config.enter_env:
        env_dir = os.path.join(config.base_dir, 'env')

        if not os.path.exists(env_dir):
            print("creating venv environment...")
            args = ['python', '-m', 'venv', '--system-site-packages', env_dir]

            ret = subprocess.Popen(args, cwd=config.base_dir).wait()

            if ret != 0:
                raise Exception("venv failed. exit code: {}. command line '{}'. working dir: '{}'."
                                .format(ret, "' '".join(args), config.base_dir))

        if not os.path.exists(os.path.join(env_dir, 'bin', 'transcrypt')) and not os.path.exists(
                os.path.join(env_dir, 'scripts', 'transcrypt.exe')):
            print("installing transcrypt into env...")

            requirements_file = os.path.join(config.base_dir, 'requirements.txt')

            pip_executable = config.pip_executable()

            if not pip_executable:
                raise Exception("pip binary not found at any of {}".format(possible_pip_binary_paths(config)))

            install_args = [pip_executable, 'install', '-r', requirements_file]

            ret = subprocess.Popen(install_args, cwd=config.base_dir).wait()

            if ret != 0:
                raise Exception("pip install failed. exit code: {}. command line '{}'. working dir: '{}'."
                                .format(ret, "' '".join(install_args), config.base_dir))

    else:
        if not shutil.which('transcrypt'):
            print("installing transcrypt using 'pip'...")

            requirements_file = os.path.join(config.base_dir, 'requirements.txt')

            pip_executable = config.pip_executable()

            if not pip_executable:
                raise Exception("pip binary not found at any of {}".format(possible_pip_binary_paths(config)))

            install_args = [pip_executable, 'install', '-r', requirements_file]

            ret = subprocess.Popen(install_args, cwd=config.base_dir).wait()

            if ret != 0:
                raise Exception("pip install failed. exit code: {}. command line '{}'. working dir: '{}'."
                                .format(ret, "' '".join(install_args), config.base_dir))

def install_node_dependencies(config):
    """
    Creates a virtualenv environment in the `env/` folder, and attempts to install `transcrypt` into it.

    If `enter-env` is False in the `config.json` file, this will instead install `transcrypt`
    into the default location for the `pip` binary which is in the path.

    :type config: Configuration
    """
    if config.rollup_executable() is not None:
        return
    node_modules = os.path.join(config.base_dir, "node_modules")
    if os.path.exists(node_modules):
        raise Exception("node_modules exists, but still can't find rollup! Have you used `npm install` to install dependencies?")
    npm = config.find_misc_executable('npm')
    if npm is None:
        raise Exception("npm not found! tried paths: {}".format(possible_rollup_binary_paths(config)))

    install_args = [npm, "install"]

    ret = subprocess.Popen(install_args, cwd=config.base_dir).wait()

    if ret != 0:
        raise Exception("npm install failed. exit code: {}. command line '{}'. working dir: '{}'."
                        .format(ret, "' '".join(install_args), config.base_dir))



def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config = load_config(base_dir)
    install_env(config)
    install_node_dependencies(config)

    if config.flatten:
        expander_control = file_expander.FileExpander(base_dir)
        expander_control.expand_files()

    build(config)
    upload(config)


if __name__ == "__main__":
    main()
