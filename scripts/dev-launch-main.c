#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* LaunchServices starts a native main; Bash retains the focus/open behavior. */
int main(void) {
    char executable[PATH_MAX], resolved[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0 || !realpath(executable, resolved)) {
        perror("Openbase launcher path");
        return 1;
    }
    char *name = strrchr(resolved, '/');
    if (!name) return 1;
    *name = '\0';
    int length = snprintf(script, sizeof(script), "%s/../Resources/launch-dashboard.sh", resolved);
    if (length < 0 || length >= (int)sizeof(script)) return 1;
    execl("/bin/bash", "bash", script, (char *)NULL);
    perror("Openbase dashboard launch");
    return 1;
}
