import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agate_autoport import porter, store as store_mod  # noqa: E402
from agate_autoport.geode_pkg import ModPackage, PackageError, read_manifest  # noqa: E402
from agate_autoport.index import IndexClient  # noqa: E402
from agate_autoport.versions import gd_key, satisfies, semver_key  # noqa: E402
from mock_index import MockIndex, make_geode, sha256  # noqa: E402


def manifest(mod_id="a.mod", version="v1.0.0", gd="2.2074", **kw):
    m = {"geode": "v5.0.0", "gd": {"win": gd, "mac": gd}, "id": mod_id, "name": mod_id,
         "developer": "t", "version": version}
    m.update(kw)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.geode = self.tmp / "geode"
        (self.geode / "mods").mkdir(parents=True)
        self.index = MockIndex().start()
        self.addCleanup(self.index.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def install_mod(self, m, native=True, name=None):
        p = self.geode / "mods" / (name or f"{m['id']}.geode")
        make_geode(p, m, native=native)
        return p

    def offer(self, m, native=True, **kw):
        tmp = self.tmp / f"offer-{m['id']}-{m['version']}.geode"
        data = make_geode(tmp, m, native=native)
        self.index.offer(m, data, **kw)
        return data

    def ctx(self, **kw):
        args = dict(store=store_mod.Store(self.geode), platform="win",
                    client=IndexClient(self.index.base + "/v1", require_https=False),
                    target_gd="2.2081", loader_tag="v9.9.9")
        args.update(kw)
        return porter.Context(**args)

    def mods(self):
        return {p.name: ModPackage.load(p) for p in (self.geode / "mods").glob("*.geode")}


class TestVersions(unittest.TestCase):
    def test_gd_order(self):
        order = ["2.206", "2.207", "2.2074", "2.2081", "2.209", "2.2091"]
        self.assertEqual(sorted(order, key=gd_key), order)

    def test_semver_and_deps(self):
        self.assertLess(semver_key("v1.0.0-beta.1"), semver_key("v1.0.0"))
        self.assertTrue(satisfies("v1.8.0", ">=v1.2.5"))
        self.assertFalse(satisfies("v2.0.0", ">=v1.2.5"))   # misma major, según la doc de Geode
        self.assertTrue(satisfies("v1.0.0", "=v1.0.0"))


class TestPackages(Base):
    def test_traversal_rejected(self):
        p = self.tmp / "evil.geode"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("mod.json", "{}")
            z.writestr("../evil.txt", "x")
        with self.assertRaises(PackageError):
            read_manifest(p)

    def test_scan_classifies(self):
        self.install_mod(manifest("old.mod"))
        self.install_mod(manifest("cur.mod", gd="2.2081"))
        m_any = manifest("any.mod"); m_any["gd"] = "*"
        self.install_mod(m_any)
        m_mac = manifest("mac.only"); m_mac["gd"] = {"mac": "2.2074"}
        self.install_mod(m_mac)
        outdated, notes = porter.scan(self.ctx())
        self.assertEqual([p.id for p in outdated], ["old.mod"])
        self.assertEqual(notes, [])


class TestIndexStrategy(Base):
    def test_update_from_index_with_backup(self):
        self.install_mod(manifest("a.mod", "v1.0.0"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        rep = porter.run(self.ctx())
        self.assertEqual([o.status for o in rep.outcomes], ["updated"])
        new = self.mods()["a.mod.geode"]
        self.assertEqual((new.version, new.gd_target("win")), ("v1.0.1", "2.2081"))
        backups = list((self.geode / "agate" / "backups" / "a.mod").glob("*.geode"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(ModPackage.load(backups[0]).version, "v1.0.0")
        self.assertEqual(store_mod.Store(self.geode).registry()["a.mod"]["source"], "index")

    def test_hash_mismatch_leaves_mod_untouched(self):
        p = self.install_mod(manifest("a.mod"))
        before = p.read_bytes()
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"), hash_override="0" * 64)
        rep = porter.run(self.ctx())
        self.assertEqual(rep.outcomes[0].status, "failed")
        self.assertIn("SHA-256", rep.outcomes[0].detail)
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse(list((self.geode / "agate" / "backups").rglob("*.geode")))

    def test_missing_hash_rejected(self):
        self.install_mod(manifest("a.mod"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"), no_hash=True)
        self.assertEqual(porter.run(self.ctx()).outcomes[0].status, "failed")

    def test_https_required(self):
        self.install_mod(manifest("a.mod"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        strict = IndexClient(self.index.base + "/v1", require_https=True)
        rep = porter.run(self.ctx(client=strict))
        self.assertEqual(rep.outcomes[0].status, "failed")

    def test_index_package_with_wrong_gd_is_not_trusted(self):
        p = self.install_mod(manifest("a.mod"))
        before = p.read_bytes()
        # El servidor "promete" 2.2081 pero el paquete real sigue apuntando a 2.2074.
        data = self.offer(manifest("a.mod", "v1.0.1", "2.2074"))
        self.index.versions["a.mod"]["gd"] = {"win": "2.2081"}
        rep = porter.run(self.ctx())
        self.assertEqual(rep.outcomes[0].status, "skipped")
        self.assertEqual(p.read_bytes(), before)

    def test_no_downgrade(self):
        self.install_mod(manifest("a.mod", "v2.0.0"))
        self.offer(manifest("a.mod", "v1.0.0", "2.2081"))
        self.assertEqual(porter.run(self.ctx()).outcomes[0].status, "skipped")

    def test_wrong_mod_id_in_package(self):
        self.install_mod(manifest("a.mod"))
        data = self.offer(manifest("b.mod", "v1.0.1", "2.2081"))
        self.index.versions["a.mod"] = self.index.versions.pop("b.mod")
        self.assertEqual(porter.run(self.ctx()).outcomes[0].status, "failed")

    def test_dependency_installed(self):
        self.install_mod(manifest("a.mod"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081", dependencies={"dep.mod": ">=v1.0.0"}))
        self.offer(manifest("dep.mod", "v1.2.0", "2.2081"))
        rep = porter.run(self.ctx())
        self.assertEqual([o.status for o in rep.outcomes], ["updated", "installed-dependency"])
        self.assertIn("dep.mod.geode", self.mods())


class TestFallbacks(Base):
    def test_resource_only_is_retargeted_keeping_other_platforms(self):
        m = manifest("res.mod", gd="2.2074"); m["gd"]["mac"] = "2.2074"
        self.install_mod(m, native=False)
        rep = porter.run(self.ctx())
        self.assertEqual(rep.outcomes[0].status, "retargeted")
        new = self.mods()["res.mod.geode"]
        self.assertEqual(new.gd_target("win"), "2.2081")
        self.assertEqual(new.gd_target("mac"), "2.2074")  # otras plataformas intactas
        with zipfile.ZipFile(new.path) as z:
            self.assertEqual(z.read("resources/readme.txt"), b"hola")

    def test_native_mod_is_never_retargeted(self):
        p = self.install_mod(manifest("nat.mod"), native=True)
        before = p.read_bytes()
        rep = porter.run(self.ctx())
        self.assertEqual(rep.outcomes[0].status, "skipped")
        self.assertIn("--allow-build", rep.outcomes[0].detail)
        self.assertEqual(p.read_bytes(), before)

    def _fake_runner(self, calls):
        def runner(cmd, cwd, timeout):
            calls.append(cmd)
            if cmd[:2] == ["git", "clone"]:
                src = Path(cmd[-1]); src.mkdir(parents=True)
                (src / "mod.json").write_text(json.dumps(manifest("nat.mod", "v1.0.0")))
            elif cmd[:2] == ["geode", "build"]:
                m = json.loads((Path(cwd) / "mod.json").read_text())
                (Path(cwd) / "build").mkdir()
                make_geode(Path(cwd) / "build" / "nat.mod.geode", m, native=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return runner

    def test_build_from_source_when_enabled(self):
        self.install_mod(manifest("nat.mod"), native=True)
        self.index.repos["nat.mod"] = "https://github.com/someone/nat-mod"
        calls = []
        rep = porter.run(self.ctx(allow_build=True, runner=self._fake_runner(calls)))
        self.assertEqual(rep.outcomes[0].status, "built", rep.outcomes[0].detail)
        new = self.mods()["nat.mod.geode"]
        self.assertEqual(new.gd_target("win"), "2.2081")
        self.assertEqual(new.manifest["geode"], "v9.9.9")  # SDK/loader actual
        self.assertTrue(any(c[:2] == ["geode", "build"] for c in calls))

    def test_build_rejects_unlisted_git_host(self):
        self.install_mod(manifest("nat.mod"), native=True)
        self.index.repos["nat.mod"] = "https://evil.example/x/y"
        calls = []
        rep = porter.run(self.ctx(allow_build=True, runner=self._fake_runner(calls)))
        self.assertEqual(rep.outcomes[0].status, "skipped")
        self.assertEqual(calls, [])

    def test_build_failure_keeps_original(self):
        p = self.install_mod(manifest("nat.mod"), native=True)
        before = p.read_bytes()
        self.index.repos["nat.mod"] = "https://github.com/someone/nat-mod"

        def runner(cmd, cwd, timeout):
            if cmd[:2] == ["git", "clone"]:
                src = Path(cmd[-1]); src.mkdir(parents=True)
                (src / "mod.json").write_text(json.dumps(manifest("nat.mod")))
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="error: Foo::bar no existe")
        rep = porter.run(self.ctx(allow_build=True, runner=runner))
        self.assertEqual(rep.outcomes[0].status, "failed")
        self.assertEqual(p.read_bytes(), before)


class TestGuardsAndSafety(Base):
    def test_older_installed_gd_blocks_porting(self):
        p = self.install_mod(manifest("a.mod"))
        before = p.read_bytes()
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        rep = porter.run(self.ctx(installed_gd="2.2074"))
        self.assertTrue(rep.skipped_reason)
        self.assertEqual(rep.outcomes, [])
        self.assertEqual(p.read_bytes(), before)
        rep = porter.run(self.ctx(installed_gd="2.2074", force=True))
        self.assertEqual(rep.outcomes[0].status, "updated")

    def test_newer_installed_gd_blocks_porting(self):
        self.install_mod(manifest("a.mod"))
        rep = porter.run(self.ctx(installed_gd="2.2091"))
        self.assertIn("más reciente", rep.skipped_reason)

    def test_dry_run_changes_nothing(self):
        p = self.install_mod(manifest("a.mod"))
        before = p.read_bytes()
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        rep = porter.run(self.ctx(dry_run=True))
        self.assertEqual(rep.outcomes[0].status, "would-updated")
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse((self.geode / "agate" / "ported.json").exists())

    def test_locked_file_goes_pending_then_applies(self):
        self.install_mod(manifest("a.mod"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        real = os.replace

        def locked(src, dst):
            if str(dst).endswith("a.mod.geode") and "pending" not in str(src):
                raise PermissionError("bloqueado")
            return real(src, dst)
        with mock.patch("os.replace", locked):
            rep = porter.run(self.ctx())
        self.assertEqual(rep.outcomes[0].applied, "pending")
        self.assertEqual(self.mods()["a.mod.geode"].version, "v1.0.0")
        porter.run(self.ctx())  # siguiente arranque: aplica lo pendiente
        self.assertEqual(self.mods()["a.mod.geode"].version, "v1.0.1")

    def test_rollback(self):
        self.install_mod(manifest("a.mod", "v1.0.0"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        porter.run(self.ctx())
        self.assertEqual(self.mods()["a.mod.geode"].version, "v1.0.1")
        self.assertIsNotNone(store_mod.Store(self.geode).rollback("a.mod"))
        self.assertEqual(self.mods()["a.mod.geode"].version, "v1.0.0")

    def test_corrupt_package_is_reported_not_fatal(self):
        (self.geode / "mods" / "broken.geode").write_bytes(b"no soy un zip")
        self.install_mod(manifest("ok.mod"), native=False)
        rep = porter.run(self.ctx())
        statuses = {o.mod_id: o.status for o in rep.outcomes}
        self.assertEqual(statuses["broken"], "failed")
        self.assertEqual(statuses["ok.mod"], "retargeted")


class TestCLI(Base):
    def test_cli_end_to_end(self):
        from agate_autoport.cli import main
        self.install_mod(manifest("a.mod"))
        self.offer(manifest("a.mod", "v1.0.1", "2.2081"))
        with mock.patch("agate_autoport.cli.IndexClient",
                        lambda base, user_agent: IndexClient(self.index.base + "/v1", require_https=False)):
            code = main(["--geode-dir", str(self.geode), "--platform", "win", "--installed-gd", "2.2081", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(self.mods()["a.mod.geode"].version, "v1.0.1")
        last = json.loads((self.geode / "agate" / "last-run.json").read_text())
        self.assertEqual(last["outcomes"][0]["status"], "updated")


if __name__ == "__main__":
    unittest.main(verbosity=2)
