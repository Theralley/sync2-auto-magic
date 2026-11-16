/*
 * Read MC13892 identification, SW1 presets and mode configuration through PMI1:.
 * Usage: s2ampmic.exe <report folder>. Ordinary application, COREDLL only.
 * No SDK DLL, driver installation, physical memory access, voltage/clock writes,
 * ADC or interrupt reads. Only registers 7, 24 and 28; no caller-supplied register.
 *
 * ABI: Freescale MC13892 pmic_ioctl.h / SDK pmic_lla.cpp (PDK1_9), corroborated
 * by the i.MX51 CE 6.0 BSP manual, chapter 19. Reads 7/24 worked in the car on
 * 2026-11-16; the register-28 read has not been tried there.
 * See docs/CLOCK-METHOD.md for provenance and what the output cannot establish.
 */
#include <windows.h>
#include <string.h>

/* pure: begin (host tests execute this same sampling/decoding logic) */
typedef int (*RegisterReader)(unsigned long, unsigned long *, void *);

static int sample_pmic(RegisterReader read_register, void *context,
                       unsigned long *identity, unsigned long *sw1, unsigned long *mode_config)
{
    if (!read_register(7, identity, context))
        return 1;
    /* MC13892 identification: ICID = 7, unused bit 5 = 0, ICIDCODE = 2.
     * Reject an untouched output buffer and other PMICs before reading SW1. */
    if (*identity > 0xffffffUL || (*identity & 0x1e0UL) != 0x1c0UL ||
        ((*identity >> 13) & 0x3fUL) != 2)
        return 2;
    if (!read_register(24, sw1, context))
        return 3;
    /* MC13892 Rev.19 table 47, note 71: SW1 does not support the high range.
     * Reject SW1HI rather than decoding its fields as ordinary 600 mV presets. */
    if (*sw1 > 0xffffffUL || (*sw1 & 0x800000UL))
        return 4;
    if (!read_register(28, mode_config, context))
        return 7;
    /* MC13892 Rev.19 table 140: bits 9 and 23 are reserved and read as zero.
     * Keep a mismatched response unavailable instead of interpreting its mode. */
    return *mode_config <= 0xffffffUL && !(*mode_config & 0x800200UL) ? 0 : 8;
}

static unsigned long sw1_mv(unsigned long value, unsigned int shift)
{
    return 600 + 25 * ((value >> shift) & 31);
}
/* pure: end */

/* CTL_CODE(FILE_DEVICE_UNKNOWN, 0x1000, METHOD_BUFFERED, FILE_ANY_ACCESS).
 * This is the reference PMIC register READ request, not IOCTL_POWER_SET. */
#define PMIC_READ_REGISTER 0x00224000UL
static HANDLE output = INVALID_HANDLE_VALUE;
static int output_failed;
static DWORD device_error;

static void put(const char *text)
{
    DWORD remaining = (DWORD)strlen(text);
    while (remaining && !output_failed) {
        DWORD written = 0;
        if (!WriteFile(output, text, remaining, &written, NULL) || !written || written > remaining) {
            output_failed = 1;
            break;
        }
        remaining -= written;
        text += written;
    }
}

static void number(unsigned long value)
{
    char text[12];
    unsigned int i = sizeof(text) - 1;
    text[i] = '\0';
    do {
        text[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value && i);
    put(text + i);
}

static void line_end(void)
{
    put("\r\n");
    if (!FlushFileBuffers(output))
        output_failed = 1;
}

static int device_read(unsigned long index, unsigned long *value, void *context)
{
    DWORD selector = (DWORD)index, result = 0xffffffffUL;
    if (index != 7 && index != 24 && index != 28)
        return 0;
    /* DWORD input/output, matching PmicRegisterRead. The reference driver does
     * not populate bytes-returned; use the same NULL argument as its SDK.
     * The sentinel and identity check prevent a no-op success being accepted. */
    if (!DeviceIoControl((HANDLE)context, PMIC_READ_REGISTER, &selector, sizeof(selector),
                         &result, sizeof(result), NULL, NULL)) {
        device_error = GetLastError();
        return 0;
    }
    *value = result;
    put("R|");
    number(index);
    put("|");
    number(result);
    line_end();
    return !output_failed;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    WCHAR folder[MAX_PATH], path[MAX_PATH], *end;
    HANDLE device;
    unsigned long identity = 0, sw1 = 0, mode_config = 0;
    int result;
    (void)instance;
    (void)previous;
    (void)show;

    while (*command == L' ' || *command == L'"')
        command++;
    if (!*command || wcslen(command) + 24 >= MAX_PATH)
        return 1;
    wcscpy(folder, command);
    end = folder + wcslen(folder);
    while (end > folder && (end[-1] == L' ' || end[-1] == L'"' || end[-1] == L'\\'))
        *--end = L'\0';
    if (!*folder)
        return 1;
    wcscpy(path, folder);
    wcscat(path, L"\\pmic.txt");
    output = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE)
        return 2;
    put("S|s2am-pmic-v2|PMI1:|R7/R24 car-verified; R28 untested in car");
    line_end();
    /* The reference driver uses a shared read/write handle even for its read
     * request. This program never sends a write or power-state request. */
    device = CreateFileW(L"PMI1:", GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                         FILE_FLAG_RANDOM_ACCESS, NULL);
    if (device == INVALID_HANDLE_VALUE || !device) {
        device_error = GetLastError();
        result = 5;
    } else {
        result = output_failed ? 6 : sample_pmic(device_read, device, &identity, &sw1, &mode_config);
        CloseHandle(device);
    }
    if (!result) {
        put("V|SW1 normal preset mV|"); number(sw1_mv(sw1, 0)); line_end();
        put("V|SW1 DVS preset mV|"); number(sw1_mv(sw1, 5)); line_end();
        put("V|SW1 standby preset mV|"); number(sw1_mv(sw1, 10)); line_end();
        put("N|active voltage, CPU rail mapping and temperature remain unknown");
        line_end();
        put("T|complete");
    } else {
        put("E|stage "); number((unsigned long)result);
        put("|system error "); number(device_error);
        line_end();
        put("T|unavailable");
    }
    line_end();
    CloseHandle(output);
    if (output_failed)
        return 3;  /* no completion marker for a partial/lost report */
    wcscpy(path, folder);
    wcscat(path, L"\\pmic-done.txt");
    output = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE)
        return 4;
    put(result ? "T|unavailable" : "T|complete");
    line_end();
    CloseHandle(output);
    return result || output_failed ? 5 : 0;
}
