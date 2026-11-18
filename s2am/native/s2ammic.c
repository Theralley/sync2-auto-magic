/* Microphone probe: which recording devices this SYNC offers, and whether sound comes
 * out of them. Usage: s2ammic.exe <report folder>.
 *
 * It lists the wave-in, wave-out and mixer devices, then records about three seconds from
 * the default device (WAVE_MAPPER, which is what AutoKit opens: AutoKit.exe 0x266e8) and
 * from each wave-in device, in the first of a few common formats the device accepts.
 * For each recording it writes how much arrived and how loud it was, and keeps the sound
 * as mic-<device>-<rate>.wav. Nothing on the car is changed: no setting, no file outside
 * the report folder. A device that delivers nothing is given up after five seconds.
 * Every step is written to mic.txt before the next one starts, so a call that never
 * returns shows where it stopped; mic-done.txt is written last.
 * It never runs longer than LIFE_MS: a second thread ends the process then, which also
 * closes the device, and the job ends it as well if it is still there after its wait.
 * A recording whose buffer the driver will not give back is not freed, and ends the probe.
 */
#include <windows.h>
#include <mmsystem.h>
#include <string.h>

#define SECONDS 3
#define GIVE_UP_MS 5000
#define POLL_MS 100
#define MAX_DEVICES 6
#define LIFE_MS 75000   /* the job waits 90 s */
#define CLEANUP_TRIES 10

static HANDLE report = INVALID_HANDLE_VALUE;
static WCHAR folder[MAX_PATH];

static void put(const char *text)
{
    DWORD written;
    if (report != INVALID_HANDLE_VALUE)
        WriteFile(report, text, (DWORD)strlen(text), &written, NULL);
}

static void number(DWORD value)
{
    char digits[11];
    int i = 10;
    digits[i] = 0;
    do {
        digits[--i] = (char)('0' + value % 10);
        value /= 10;
    } while (value && i);
    put(digits + i);
}

static void field(const char *name, DWORD value)
{
    put("|");
    put(name);
    put(" ");
    number(value);
}

static void wide(const WCHAR *text, int limit)
{
    char out[80];
    int i = 0;
    while (*text && i < limit && i < 79) {
        out[i++] = (*text >= 32 && *text < 127 && *text != L'|') ? (char)*text : '?';
        text++;
    }
    out[i] = 0;
    put(out);
}

static void line_end(void)
{
    put("\r\n");
    if (report != INVALID_HANDLE_VALUE)
        FlushFileBuffers(report);
}

static HANDLE create(const WCHAR *name)
{
    WCHAR path[MAX_PATH];
    if (wcslen(folder) + wcslen(name) + 2 > MAX_PATH)
        return INVALID_HANDLE_VALUE;
    wcscpy(path, folder);
    wcscat(path, L"\\");
    wcscat(path, name);
    return CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL, NULL);
}

static void le32(unsigned char *at, DWORD value)
{
    at[0] = (unsigned char)value;
    at[1] = (unsigned char)(value >> 8);
    at[2] = (unsigned char)(value >> 16);
    at[3] = (unsigned char)(value >> 24);
}

/* The recording as a plain WAV file, so it can be listened to on the Mac. */
static void save(UINT device, const WAVEFORMATEX *format, const char *data, DWORD bytes)
{
    WCHAR name[40];
    unsigned char head[44];
    DWORD written;
    HANDLE file;
    if (device == WAVE_MAPPER)
        wsprintfW(name, L"mic-default-%u.wav", (unsigned)format->nSamplesPerSec);
    else
        wsprintfW(name, L"mic-%u-%u.wav", (unsigned)device, (unsigned)format->nSamplesPerSec);
    file = create(name);
    if (file == INVALID_HANDLE_VALUE)
        return;
    memcpy(head, "RIFF", 4);
    le32(head + 4, 36 + bytes);
    memcpy(head + 8, "WAVEfmt ", 8);
    le32(head + 16, 16);
    head[20] = 1;
    head[21] = 0;
    head[22] = (unsigned char)format->nChannels;
    head[23] = 0;
    le32(head + 24, format->nSamplesPerSec);
    le32(head + 28, format->nAvgBytesPerSec);
    head[32] = (unsigned char)format->nBlockAlign;
    head[33] = 0;
    head[34] = 16;
    head[35] = 0;
    memcpy(head + 36, "data", 4);
    le32(head + 40, bytes);
    WriteFile(file, head, sizeof(head), &written, NULL);
    WriteFile(file, data, bytes, &written, NULL);
    CloseHandle(file);
}

static const struct {
    DWORD rate;
    WORD channels;
} formats[] = {{16000, 1}, {8000, 1}, {44100, 2}, {48000, 2}, {44100, 1}, {48000, 1}};

/* One recording. "open" lines carry the system's answer for each format tried; a "heard"
 * line follows for the one that opened. ``only`` (not 0) limits it to that sample rate.
 * FALSE when the driver would not give the buffer or the device back: the buffer and its
 * header are then left allocated, since the driver may still write to them, and nothing
 * more is recorded. */
static BOOL record(UINT device, DWORD only)
{
    WAVEFORMATEX format;
    WAVEHDR *head;
    HWAVEIN in = NULL;
    MMRESULT result = MMSYSERR_ERROR;
    MMRESULT prepared;
    int tries;
    DWORD size, waited = 0, first = 0, i, samples, peak = 0, loud = 0, nonzero = 0;
    unsigned long long sum = 0;
    char *data;
    unsigned f;
    short *sample;

    for (f = 0; f < sizeof(formats) / sizeof(formats[0]); f++) {
        if (only && formats[f].rate != only)
            continue;
        memset(&format, 0, sizeof(format));
        format.wFormatTag = WAVE_FORMAT_PCM;
        format.nChannels = formats[f].channels;
        format.nSamplesPerSec = formats[f].rate;
        format.wBitsPerSample = 16;
        format.nBlockAlign = (WORD)(format.nChannels * 2);
        format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;
        put("open");
        field("device", device == WAVE_MAPPER ? 99 : device);
        field("rate", format.nSamplesPerSec);
        field("channels", format.nChannels);
        line_end();
        result = waveInOpen(&in, device, &format, 0, 0, CALLBACK_NULL);
        put("opened");
        field("result", result);
        line_end();
        if (result == MMSYSERR_NOERROR)
            break;
        if (only)
            return TRUE;
    }
    if (result != MMSYSERR_NOERROR)
        return TRUE;

    size = format.nAvgBytesPerSec * SECONDS;
    data = (char *)LocalAlloc(LPTR, size);
    head = (WAVEHDR *)LocalAlloc(LPTR, sizeof(WAVEHDR));
    if (!data || !head) {
        put("nomemory");
        line_end();
        if (data)
            LocalFree(data);
        if (head)
            LocalFree(head);
        result = waveInClose(in);
        put("closed");
        field("result", result);
        line_end();
        return result == MMSYSERR_NOERROR;
    }
    head->lpData = data;
    head->dwBufferLength = size;
    prepared = waveInPrepareHeader(in, head, sizeof(WAVEHDR));
    result = prepared;
    if (result == MMSYSERR_NOERROR)
        result = waveInAddBuffer(in, head, sizeof(WAVEHDR));
    if (result == MMSYSERR_NOERROR)
        result = waveInStart(in);
    put("started");
    field("result", result);
    line_end();
    if (result == MMSYSERR_NOERROR) {
        while (!(head->dwFlags & WHDR_DONE) && waited < GIVE_UP_MS) {
            Sleep(POLL_MS);
            waited += POLL_MS;
            if (!first && head->dwBytesRecorded)
                first = waited;
        }
    }
    put("stopping");
    field("waited ms", waited);
    field("done", (head->dwFlags & WHDR_DONE) != 0);
    line_end();
    /* The buffer is the driver's until the reset has given it back and the header is
     * unprepared: only then is it read, and only then may it be freed. */
    for (tries = 0; tries < CLEANUP_TRIES; tries++) {
        result = waveInReset(in);
        if (result == MMSYSERR_NOERROR && prepared == MMSYSERR_NOERROR)
            result = waveInUnprepareHeader(in, head, sizeof(WAVEHDR));
        if (result == MMSYSERR_NOERROR)
            break;
        Sleep(POLL_MS);
    }
    if (result != MMSYSERR_NOERROR) {
        put("abandoned");
        field("result", result);
        line_end();
        return FALSE;  /* buffer, header and handle stay: the process ends soon and takes them */
    }
    samples = head->dwBytesRecorded / 2;
    if (samples > size / 2)
        samples = size / 2;
    sample = (short *)data;
    for (i = 0; i < samples; i++) {
        DWORD level = (DWORD)(sample[i] < 0 ? -(int)sample[i] : sample[i]);
        if (level > peak)
            peak = level;
        if (level)
            nonzero++;
        if (level > 500)
            loud++;
        sum += level;
    }
    put("heard");
    field("device", device == WAVE_MAPPER ? 99 : device);
    field("rate", format.nSamplesPerSec);
    field("channels", format.nChannels);
    field("bytes", head->dwBytesRecorded);
    field("of", size);
    field("first data ms", first);
    field("peak", peak);
    field("average", samples ? (DWORD)(sum / samples) : 0);
    field("samples not zero", nonzero);
    field("samples above 500", loud);
    line_end();
    if (samples)
        save(device, &format, data, samples * 2);
    LocalFree(data);
    LocalFree(head);
    result = waveInClose(in);
    put("closed");
    field("result", result);
    line_end();
    return result == MMSYSERR_NOERROR;  /* a device that will not close: no further recording */
}

/* The probe's own limit: whatever the audio driver does, the process is gone after LIFE_MS,
 * and its device handle with it. */
static DWORD WINAPI limit(LPVOID unused)
{
    (void)unused;
    Sleep(LIFE_MS);
    TerminateProcess(GetCurrentProcess(), 4);
    return 0;
}

static void list_devices(void)
{
    UINT count, i;
    WAVEINCAPS in;
    WAVEOUTCAPS out;
    count = waveInGetNumDevs();
    put("wave in");
    field("devices", count);
    line_end();
    for (i = 0; i < count && i < 16; i++) {
        memset(&in, 0, sizeof(in));
        put("in");
        field("device", i);
        field("result", waveInGetDevCaps(i, &in, sizeof(in)));
        field("formats", in.dwFormats);
        field("channels", in.wChannels);
        put("|name ");
        wide(in.szPname, 31);
        line_end();
    }
    count = waveOutGetNumDevs();
    put("wave out");
    field("devices", count);
    line_end();
    for (i = 0; i < count && i < 16; i++) {
        memset(&out, 0, sizeof(out));
        put("out");
        field("device", i);
        field("result", waveOutGetDevCaps(i, &out, sizeof(out)));
        field("formats", out.dwFormats);
        field("channels", out.wChannels);
        put("|name ");
        wide(out.szPname, 31);
        line_end();
    }
}

/* The mixer's lines by name: where a microphone source, if the system names one, shows. */
static void list_mixers(void)
{
    UINT count = mixerGetNumDevs(), m;
    DWORD d, s;
    MIXERCAPS caps;
    MIXERLINE line;
    put("mixers");
    field("devices", count);
    line_end();
    for (m = 0; m < count && m < 4; m++) {
        memset(&caps, 0, sizeof(caps));
        put("mixer");
        field("device", m);
        field("result", mixerGetDevCaps(m, &caps, sizeof(caps)));
        field("destinations", caps.cDestinations);
        put("|name ");
        wide(caps.szPname, 31);
        line_end();
        for (d = 0; d < caps.cDestinations && d < 16; d++) {
            memset(&line, 0, sizeof(line));
            line.cbStruct = sizeof(line);
            line.dwDestination = d;
            if (mixerGetLineInfo((HMIXEROBJ)m, &line, MIXER_OBJECTF_MIXER | MIXER_GETLINEINFOF_DESTINATION))
                continue;
            put("line");
            field("mixer", m);
            field("destination", d);
            field("type", line.dwComponentType);
            field("sources", line.cConnections);
            field("controls", line.cControls);
            put("|name ");
            wide(line.szName, 63);
            line_end();
            for (s = 0; s < line.cConnections && s < 24; s++) {
                MIXERLINE source;
                memset(&source, 0, sizeof(source));
                source.cbStruct = sizeof(source);
                source.dwDestination = d;
                source.dwSource = s;
                if (mixerGetLineInfo((HMIXEROBJ)m, &source, MIXER_OBJECTF_MIXER | MIXER_GETLINEINFOF_SOURCE))
                    continue;
                put("source");
                field("mixer", m);
                field("destination", d);
                field("source", s);
                field("type", source.dwComponentType);
                field("controls", source.cControls);
                put("|name ");
                wide(source.szName, 63);
                line_end();
            }
        }
    }
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    UINT count, i;
    HANDLE done, watch;
    BOOL going;
    size_t length;
    (void)instance;
    (void)previous;
    (void)show;
    while (*command == L' ' || *command == L'"')
        command++;
    length = wcslen(command);
    while (length && (command[length - 1] == L' ' || command[length - 1] == L'"'))
        length--;
    if (!length || length >= MAX_PATH - 40)
        return 2;
    memcpy(folder, command, length * sizeof(WCHAR));
    folder[length] = 0;
    report = create(L"mic.txt");
    if (report == INVALID_HANDLE_VALUE)
        return 3;
    put("s2am-mic-v1");
    line_end();
    watch = CreateThread(NULL, 0, limit, NULL, 0, NULL);
    if (!watch) {
        put("no limit thread, nothing recorded");
        line_end();
        CloseHandle(report);
        return 5;
    }
    CloseHandle(watch);
    list_devices();
    list_mixers();
    going = record(WAVE_MAPPER, 16000);  /* as AutoKit opens it */
    going = going && record(WAVE_MAPPER, 8000);
    count = waveInGetNumDevs();
    for (i = 0; going && i < count && i < MAX_DEVICES; i++)
        going = record(i, 0);
    put("end");
    line_end();
    CloseHandle(report);
    done = create(L"mic-done.txt");
    if (done != INVALID_HANDLE_VALUE)
        CloseHandle(done);
    return 0;
}
