// Agate AutoPort - disparador dentro del juego.
//
// Este mod NO engancha (hook) ninguna función de GD, así que declara "gd": "*" en mod.json
// y nunca se queda obsoleto. Su única tarea es lanzar, en segundo plano y sin ventana, el
// ejecutable agate-autoport que instaló el instalador junto al juego.
//
// AVISO: este archivo no se pudo compilar en el entorno donde se escribió (no hay Geode SDK
// ni GD). Los nombres de la API de Geode usados abajo (dirs::getGeodeDir, Loader::getGameVersion,
// utils::string::utf8ToWide/pathToString, $on_mod) son los de la documentación de Geode;
// el workflow de CI lo compila y mostrará cualquier diferencia con tu versión del SDK.

#include <Geode/Geode.hpp>
#include <Geode/loader/Dirs.hpp>

#include <filesystem>
#include <string>
#include <thread>
#include <vector>

#ifdef GEODE_IS_WINDOWS
    #include <windows.h>
#else
    #include <mach-o/dyld.h>
    #include <spawn.h>
    #include <sys/wait.h>
extern char** environ;
#endif

using namespace geode::prelude;
namespace fs = std::filesystem;

namespace {

fs::path exeDir() {
#ifdef GEODE_IS_WINDOWS
    std::wstring buf(MAX_PATH * 4, L'\0');
    DWORD n = GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
    buf.resize(n);
    return fs::path(buf).parent_path();
#else
    uint32_t size = 0;
    _NSGetExecutablePath(nullptr, &size);
    std::string buf(size, '\0');
    if (_NSGetExecutablePath(buf.data(), &size) != 0) return {};
    std::error_code ec;
    return fs::weakly_canonical(fs::path(buf.c_str()), ec).parent_path();
#endif
}

fs::path toolPath() {
    auto dir = exeDir();
#ifdef GEODE_IS_WINDOWS
    // <carpeta del juego>/agate/agate-autoport.exe
    return dir / "agate" / "agate-autoport.exe";
#else
    // <App>/Contents/MacOS  ->  <App>/Contents/Resources/agate/agate-autoport
    return dir.parent_path() / "Resources" / "agate" / "agate-autoport";
#endif
}

bool spawnDetached(fs::path const& exe, std::vector<std::string> const& args) {
#ifdef GEODE_IS_WINDOWS
    std::wstring cmd = L"\"" + exe.wstring() + L"\"";
    for (auto const& a : args) {
        cmd += L" \"" + geode::utils::string::utf8ToWide(a) + L"\"";
    }
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    BOOL ok = CreateProcessW(
        exe.c_str(), cmd.data(), nullptr, nullptr, FALSE,
        CREATE_NO_WINDOW | DETACHED_PROCESS, nullptr, nullptr, &si, &pi
    );
    if (ok) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    return ok != FALSE;
#else
    std::vector<std::string> storage{exe.string()};
    storage.insert(storage.end(), args.begin(), args.end());
    std::vector<char*> argv;
    for (auto& s : storage) argv.push_back(s.data());
    argv.push_back(nullptr);

    pid_t pid = 0;
    if (posix_spawn(&pid, exe.c_str(), nullptr, nullptr, argv.data(), environ) != 0) return false;
    std::thread([pid] {  // evita procesos zombi
        int status = 0;
        waitpid(pid, &status, 0);
    }).detach();
    return true;
#endif
}

} // namespace

$on_mod(Loaded) {
    auto* self = Mod::get();
    if (!self->getSettingValue<bool>("auto-update")) {
        log::info("Agate AutoPort desactivado en los ajustes");
        return;
    }

    auto tool = toolPath();
    std::error_code ec;
    if (!fs::exists(tool, ec)) {
        log::warn("Agate AutoPort: no se encontró el actualizador en {}", geode::utils::string::pathToString(tool));
        return;
    }

#ifdef GEODE_IS_WINDOWS
    constexpr char const* platform = "win";
#else
    constexpr char const* platform = "mac";
#endif

    std::vector<std::string> args = {
        "run", "--notify",
        "--platform", platform,
        "--geode-dir", geode::utils::string::pathToString(dirs::getGeodeDir()),
        "--installed-gd", Loader::get()->getGameVersion(),
    };
    if (self->getSettingValue<bool>("allow-build")) args.push_back("--allow-build");

    if (spawnDetached(tool, args)) {
        log::info("Agate AutoPort: comprobando compatibilidad de mods con la última versión de GD");
    } else {
        log::error("Agate AutoPort: no se pudo lanzar el actualizador");
    }
}
