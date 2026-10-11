// Native main executable for the Openbase developer launcher bundle that
// scripts/dev-launch publishes to /Applications/Openbase.app.
//
// LaunchServices on macOS 15 refuses to open a bundle whose main executable
// is a shell script (error -10669), while a Mach-O binary that runs the same
// script opens fine (fresh-VM developer QA, 2026-10-10). This binary execs
// the launcher script shipped in Contents/Resources through /bin/bash, so
// the script keeps the process, and the LaunchServices identity, it had when
// it was the main executable itself. All launch and focus logic stays in the
// script.
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0) {
        fputs("openbase launcher: executable path is too long\n", stderr);
        return 1;
    }
    char resolved[PATH_MAX];
    if (realpath(executable, resolved) == NULL) {
        perror("openbase launcher: realpath");
        return 1;
    }
    // <bundle>/Contents/MacOS/Openbase -> <bundle>/Contents
    char macos_dir[PATH_MAX];
    snprintf(macos_dir, sizeof(macos_dir), "%s", dirname(resolved));
    char contents_dir[PATH_MAX];
    snprintf(contents_dir, sizeof(contents_dir), "%s", dirname(macos_dir));
    char script[PATH_MAX];
    snprintf(script, sizeof(script), "%s/Resources/openbase-launch.sh", contents_dir);

    char **args = calloc((size_t)argc + 2, sizeof(char *));
    if (args == NULL) {
        perror("openbase launcher: calloc");
        return 1;
    }
    args[0] = "/bin/bash";
    args[1] = script;
    for (int i = 1; i < argc; i++) {
        args[i + 1] = argv[i];
    }
    execv("/bin/bash", args);
    perror("openbase launcher: execv /bin/bash");
    return 1;
}
