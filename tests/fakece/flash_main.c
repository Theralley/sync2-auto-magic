/* Runs s2amflash.c's WinMain against the stand-in API.
 * flash <registry> <backup> <command>
 *   registry: four items, a number, "a" (absent) or "s" (a text value), or "nokey"
 *   backup:   the backup file's text, or "-" for none
 * Prints the registry, the backup and staging file, the report and the return value. */
#include "s2amflash.c"

static void show_file(const char *label, const wchar_t *path)
{
    struct fake_file *file = fake_find(path);
    printf("%s ", label);
    if (!file) printf("-");
    else fwrite(file->data, 1, file->length, stdout);
    printf("\n");
}

int main(int argc, char **argv)
{
    wchar_t command[600];
    char *item, *spec;
    int i, result;
    if (argc != 4) return 9;
    spec = strdup(argv[1]);
    if (!strcmp(spec, "nokey")) fake_key = 0;
    else
        for (i = 0, item = strtok(spec, ","); i < FAKE_VALUES; i++, item = strtok(NULL, ",")) {
            if (!item) return 9;
            fake_reg[i].present = strcmp(item, "a") != 0;
            fake_reg[i].type = strcmp(item, "s") ? REG_DWORD : REG_SZ;
            fake_reg[i].value = (DWORD)strtoul(item, NULL, 10);
        }
    if (strcmp(argv[2], "-")) {
        fake_files[0].used = 1;
        wcscpy(fake_files[0].path, L"\\SyncExtendedPack\\_s2am\\flash-backup.txt");
        fake_files[0].length = strlen(argv[2]);
        memcpy(fake_files[0].data, argv[2], fake_files[0].length);
    }
    mbstowcs(command, argv[3], 599);
    result = WinMain(NULL, NULL, command, 0);
    printf("REG");
    for (i = 0; i < FAKE_VALUES; i++) {
        if (!fake_reg[i].present) printf(" a");
        else if (fake_reg[i].type != REG_DWORD) printf(" s");
        else printf(" %u", (unsigned)fake_reg[i].value);
    }
    printf("\n");
    show_file("BACKUP", L"\\SyncExtendedPack\\_s2am\\flash-backup.txt");
    show_file("STAGING", L"\\SyncExtendedPack\\_s2am\\flash-backup.new");
    show_file("DONE", L"\\USB Disk\\s2am\\reports\\job 1\\flash-done.txt");
    show_file("REPORT", L"\\USB Disk\\s2am\\reports\\job 1\\flash.txt");
    printf("RET %d lock %d\n", result, fake_lock);
    return 0;
}
