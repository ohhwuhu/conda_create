"""Unit tests for the pure logic in conda_api.py (no conda required)."""

import os
import unittest

import conda_api


class TestBuildCreateArgs(unittest.TestCase):
    def test_named_env(self):
        args = conda_api.build_create_args("conda.exe", name="myname", python_version="3.11")
        self.assertEqual(args, ["conda.exe", "create", "-y", "-n", "myname", "python=3.11"])

    def test_prefix_env(self):
        args = conda_api.build_create_args("conda.exe", prefix=r"C:\tmp\env", python_version="3.10")
        self.assertEqual(args, ["conda.exe", "create", "-y", "-p", r"C:\tmp\env", "python=3.10"])

    def test_name_precedence_over_prefix(self):
        args = conda_api.build_create_args("conda.exe", name="n", prefix="p", python_version="3.9")
        self.assertIn("-n", args)

    def test_missing_target_raises(self):
        with self.assertRaises(ValueError):
            conda_api.build_create_args("conda.exe", python_version="3.9")

    def test_missing_version_raises(self):
        with self.assertRaises(ValueError):
            conda_api.build_create_args("conda.exe", name="n", python_version="  ")


class TestBuildRemoveArgs(unittest.TestCase):
    def test_named(self):
        args = conda_api.build_remove_args("conda.exe", name="old")
        self.assertEqual(args, ["conda.exe", "env", "remove", "-y", "-n", "old"])

    def test_prefix(self):
        args = conda_api.build_remove_args("conda.exe", prefix=r"C:\tmp\env")
        self.assertEqual(args, ["conda.exe", "env", "remove", "-y", "-p", r"C:\tmp\env"])

    def test_missing_target_raises(self):
        with self.assertRaises(ValueError):
            conda_api.build_remove_args("conda.exe")


class TestParseEnvPaths(unittest.TestCase):
    def setUp(self):
        self.base = r"D:\miniconda3"
        self.envs_dirs = [r"D:\miniconda3\envs", r"C:\Users\me\.conda\envs"]

    def test_base_and_named_envs(self):
        paths = [
            r"D:\miniconda3",
            r"D:\miniconda3\envs\py12",
            r"C:\Users\me\.conda\envs\others",
            r"C:\Somewhere\prefix_env",
        ]
        envs = conda_api.parse_env_paths(paths, self.base, self.envs_dirs)
        by_name = {e["name"]: e for e in envs}
        self.assertEqual(by_name["base"]["is_base"], True)
        self.assertEqual(by_name["py12"]["is_base"], False)
        self.assertEqual(by_name["others"]["name"], "others")
        # prefix env outside envs_dirs keeps its full path as the name
        self.assertEqual(by_name[r"C:\Somewhere\prefix_env"]["name"], r"C:\Somewhere\prefix_env")
        # base always sorts first
        self.assertEqual(envs[0]["name"], "base")

    def test_empty(self):
        self.assertEqual(conda_api.parse_env_paths([], self.base, self.envs_dirs), [])

    def test_case_insensitive_base_match(self):
        paths = [r"d:\MINICONDA3"]
        envs = conda_api.parse_env_paths(paths, self.base, self.envs_dirs)
        self.assertEqual(envs[0]["is_base"], True)


class TestResolvePrefixEnvPath(unittest.TestCase):
    def test_plain_dir_gets_conda_appended(self):
        self.assertEqual(conda_api.resolve_prefix_env_path(r"C:\proj\foo"), r"C:\proj\foo\.conda")

    def test_already_conda_dir_unchanged(self):
        self.assertEqual(conda_api.resolve_prefix_env_path(r"C:\proj\foo\.conda"), r"C:\proj\foo\.conda")

    def test_trailing_separator(self):
        self.assertEqual(conda_api.resolve_prefix_env_path(r"C:\proj\foo\.conda\\"), r"C:\proj\foo\.conda")

    def test_empty(self):
        self.assertEqual(conda_api.resolve_prefix_env_path("  "), "")

    def test_forward_slash(self):
        result = conda_api.resolve_prefix_env_path("C:/proj/foo").replace("/", "\\")
        self.assertEqual(result, r"C:\proj\foo\.conda")


class TestCandidateRoots(unittest.TestCase):
    def _roots(self):
        return {os.path.normcase(str(r)) for r in conda_api._candidate_roots()}

    def test_miniconda_and_anaconda_paired(self):
        roots = self._roots()
        for base in (r"D:\app", r"C:\ProgramData", "C:" + os.sep):
            for distro in ("miniconda3", "anaconda3"):
                expected = os.path.normcase(os.path.join(base, distro))
                self.assertIn(expected, roots, f"{base}\\{distro}")

    def test_home_variants(self):
        roots = self._roots()
        home = os.path.normcase(os.path.expanduser("~"))
        for name in ("miniconda3", "anaconda3"):
            self.assertIn(os.path.join(home, name), roots, name)


if __name__ == "__main__":
    unittest.main()
