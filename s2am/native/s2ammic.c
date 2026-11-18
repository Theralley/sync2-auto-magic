/* Microphone probe: which recording devices this SYNC offers, and which of them carries
 * sound, and when. Usage: s2ammic.exe <report folder>.
 *
 * It lists the wave-in, wave-out and mixer devices and what the mixer's controls are set to
 * (read only). Then it opens every wave-in device at once, each in the first of a few common
 * formats it accepts, and listens for LISTEN_SECONDS: once a second it writes how much each
 * device has delivered, so a device that only carries sound while SYNC itself listens (the
 * voice button held, a call) shows, and from which second. AutoKit opens the default device
 * (AutoKit.exe 0x266e8), which is device 0. For each device it then writes how loud it was
 * and keeps the sound as mic-<device>-<rate>.wav. Nothing on the car is changed: no setting,
 * no mixer control, no file outside the report folder.
 * Every step is written to mic.txt before the next one starts, so a call that never
 * returns shows where it stopped; mic-done.txt is written last.
 * It never runs longer than LIFE_MS: a second thread ends the process then, which also
 * closes the devices, and the job ends it as well if it is still there after its wait.
 * Buffers the driver will not give back are not freed.
 */
#include <windows.h>
#include <mmsystem.h>
#include <string.h>

#define LISTEN_SECONDS 20
#define CHUNK_MS 500
#define CHUNKS (LISTEN_SECONDS * 1000 / CHUNK_MS)
#define POLL_MS 100
#define MAX_DEVICES 16
#define MAX_CONTROLS 8
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
} formats[] = {{16000, 1}, {8000, 1}, {44100, 2}, {48000, 2}};

/* One recording device being listened to: CHUNKS buffers of CHUNK_MS each, all queued before
 * the start, so what the driver has given back by each second shows when sound flowed. */
typedef struct {
    UINT device;
    HWAVEIN in;
    WAVEFORMATEX format;
    WAVEHDR *heads;
    char *data;
    DWORD chunk;    /* bytes in one buffer */
    int prepared;   /* headers prepared, counted from the first */
    int first;      /* the first second a returned buffer held data, 0 if none */
} Ear;

static Ear ears[MAX_DEVICES];
static int ear_count;

/* Opens ``device`` in the first format it accepts and queues its buffers. Every answer of the
 * system is written. Nothing is started here. */
static void ear_open(UINT device)
{
    Ear *ear = &ears[ear_count];
    MMRESULT result = MMSYSERR_ERROR;
    unsigned f;
    int i;
    memset(ear, 0, sizeof(*ear));
    ear->device = device;
    for (f = 0; f < sizeof(formats) / sizeof(formats[0]); f++) {
        ear->format.wFormatTag = WAVE_FORMAT_PCM;
        ear->format.nChannels = formats[f].channels;
        ear->format.nSamplesPerSec = formats[f].rate;
        ear->format.wBitsPerSample = 16;
        ear->format.nBlockAlign = (WORD)(ear->format.nChannels * 2);
        ear->format.nAvgBytesPerSec = ear->format.nSamplesPerSec * ear->format.nBlockAlign;
        put("open");
        field("device", device);
        field("rate", ear->format.nSamplesPerSec);
        field("channels", ear->format.nChannels);
        line_end();
        result = waveInOpen(&ear->in, device, &ear->format, 0, 0, CALLBACK_NULL);
        put("opened");
        field("result", result);
        line_end();
        if (result == MMSYSERR_NOERROR)
            break;
    }
    if (result != MMSYSERR_NOERROR)
        return;
    ear->chunk = ear->format.nAvgBytesPerSec / (1000 / CHUNK_MS);
    ear->data = (char *)LocalAlloc(LPTR, ear->chunk * CHUNKS);
    ear->heads = (WAVEHDR *)LocalAlloc(LPTR, sizeof(WAVEHDR) * CHUNKS);
    if (!ear->data || !ear->heads) {
        put("nomemory");
        field("device", device);
        line_end();
        if (ear->data)
            LocalFree(ear->data);
        if (ear->heads)
            LocalFree(ear->heads);
        result = waveInClose(ear->in);
        put("closed");
        field("device", device);
        field("result", result);
        line_end();
        return;
    }
    for (i = 0; i < CHUNKS && result == MMSYSERR_NOERROR; i++) {
        ear->heads[i].lpData = ear->data + (DWORD)i * ear->chunk;
        ear->heads[i].dwBufferLength = ear->chunk;
        result = waveInPrepareHeader(ear->in, &ear->heads[i], sizeof(WAVEHDR));
        if (result == MMSYSERR_NOERROR) {
            ear->prepared = i + 1;
            result = waveInAddBuffer(ear->in, &ear->heads[i], sizeof(WAVEHDR));
        }
    }
    put("queued");
    field("device", device);
    field("result", result);
    line_end();
    ear_count++;  /* opened: it is closed again in ear_close, whatever happened to its buffers */
}

/* Stops one device, takes its buffers back and writes what they held. A device whose buffers
 * the driver will not give back keeps them, and its handle: they go with the process. */
static void ear_close(Ear *ear)
{
    MMRESULT result = MMSYSERR_NOERROR;
    DWORD bytes = 0, samples, i, peak = 0, loud = 0, nonzero = 0;
    unsigned long long sum = 0;
    short *sample;
    int tries, h;
    for (tries = 0; tries < CLEANUP_TRIES; tries++) {
        result = waveInReset(ear->in);
        for (h = 0; h < ear->prepared && result == MMSYSERR_NOERROR; h++)
            if (ear->heads[h].dwFlags & WHDR_PREPARED)
                result = waveInUnprepareHeader(ear->in, &ear->heads[h], sizeof(WAVEHDR));
        if (result == MMSYSERR_NOERROR)
            break;
        Sleep(POLL_MS);
    }
    if (result != MMSYSERR_NOERROR) {
        put("abandoned");
        field("device", ear->device);
        field("result", result);
        line_end();
        return;
    }
    /* The buffers are ours again. What each one holds is moved up to the start, in order. */
    for (h = 0; h < ear->prepared; h++) {
        DWORD got = ear->heads[h].dwBytesRecorded;
        if (got > ear->chunk)
            got = ear->chunk;
        got &= ~(DWORD)1;
        if (got)
            memmove(ear->data + bytes, ear->heads[h].lpData, got);
        bytes += got;
    }
    samples = bytes / 2;
    sample = (short *)ear->data;
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
    field("device", ear->device);
    field("rate", ear->format.nSamplesPerSec);
    field("channels", ear->format.nChannels);
    field("bytes", bytes);
    field("of", ear->chunk * CHUNKS);
    field("first second", (DWORD)ear->first);
    field("peak", peak);
    field("average", samples ? (DWORD)(sum / samples) : 0);
    field("samples not zero", nonzero);
    field("samples above 500", loud);
    line_end();
    if (bytes)
        save(ear->device, &ear->format, ear->data, bytes);
    LocalFree(ear->data);
    LocalFree(ear->heads);
    result = waveInClose(ear->in);
    put("closed");
    field("device", ear->device);
    field("result", result);
    line_end();
}

/* Listens on every recording device at once for LISTEN_SECONDS, so it shows which of them
 * carries sound while the user holds the voice button and talks, and from which second. */
static void listen_all(void)
{
    UINT count = waveInGetNumDevs(), i;
    int second, e, h;
    for (i = 0; i < count && i < MAX_DEVICES; i++)
        ear_open(i);
    for (e = 0; e < ear_count; e++) {
        MMRESULT result = waveInStart(ears[e].in);
        put("listening");
        field("device", ears[e].device);
        field("result", result);
        line_end();
    }
    for (second = 1; second <= LISTEN_SECONDS; second++) {
        Sleep(1000);
        put("tick");
        field("second", (DWORD)second);
        for (e = 0; e < ear_count; e++) {
            DWORD bytes = 0;
            for (h = 0; h < ears[e].prepared; h++)
                if (ears[e].heads[h].dwFlags & WHDR_DONE)
                    bytes += ears[e].heads[h].dwBytesRecorded;
            if (bytes && !ears[e].first)
                ears[e].first = second;
            put("|");
            number(ears[e].device);
            put(":");
            number(bytes);
        }
        line_end();
    }
    for (e = 0; e < ear_count; e++)
        ear_close(&ears[e]);
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

/* What one control of a mixer line is set to: read only, never written. */
static void list_controls(HMIXER mixer, const MIXERLINE *line)
{
    MIXERLINECONTROLS query;
    MIXERCONTROL *controls;
    MIXERCONTROLDETAILS details;
    MIXERCONTROLDETAILS_UNSIGNED value;
    DWORD c, count = line->cControls;
    MMRESULT result;
    if (!count)
        return;
    if (count > MAX_CONTROLS)
        count = MAX_CONTROLS;
    controls = (MIXERCONTROL *)LocalAlloc(LPTR, sizeof(MIXERCONTROL) * line->cControls);
    if (!controls)
        return;
    memset(&query, 0, sizeof(query));
    query.cbStruct = sizeof(query);
    query.dwLineID = line->dwLineID;
    query.cControls = line->cControls;
    query.cbmxctrl = sizeof(MIXERCONTROL);
    query.pamxctrl = controls;
    result = mixerGetLineControls((HMIXEROBJ)mixer, &query, MIXER_OBJECTF_HMIXER | MIXER_GETLINECONTROLSF_ALL);
    if (result != MMSYSERR_NOERROR) {
        put("controls");
        field("line", line->dwLineID);
        field("result", result);
        line_end();
        LocalFree(controls);
        return;
    }
    for (c = 0; c < count; c++) {
        memset(&details, 0, sizeof(details));
        memset(&value, 0, sizeof(value));
        details.cbStruct = sizeof(details);
        details.dwControlID = controls[c].dwControlID;
        details.cChannels = 1;
        details.cbDetails = sizeof(value);
        details.paDetails = &value;
        /* A control with several items (a selector, a list) needs one value per item: its
         * value is not read here, only that it is there and how many items it has. */
        result = controls[c].cMultipleItems ? MMSYSERR_NOTSUPPORTED :
                 mixerGetControlDetails((HMIXEROBJ)mixer, &details,
                                        MIXER_OBJECTF_HMIXER | MIXER_GETCONTROLDETAILSF_VALUE);
        put("control");
        field("line", line->dwLineID);
        field("id", controls[c].dwControlID);
        field("type", controls[c].dwControlType);
        field("read", result);
        field("value", value.dwValue);
        field("min", controls[c].Bounds.dwMinimum);
        field("max", controls[c].Bounds.dwMaximum);
        field("items", controls[c].cMultipleItems);
        field("flags", controls[c].fdwControl);
        put("|name ");
        wide(controls[c].szName, 63);
        line_end();
    }
    LocalFree(controls);
}

/* The mixer's lines and what their controls are set to: where a microphone source, a mute
 * or a selector shows, if the system has one. Every answer is written, also a refusal. */
static void list_mixers(void)
{
    UINT count = mixerGetNumDevs(), m;
    DWORD d, s;
    MIXERCAPS caps;
    MIXERLINE line;
    HMIXER mixer;
    MMRESULT result;
    put("mixers");
    field("devices", count);
    line_end();
    for (m = 0; m < count && m < 2; m++) {
        memset(&caps, 0, sizeof(caps));
        put("mixer");
        field("device", m);
        field("result", mixerGetDevCaps(m, &caps, sizeof(caps)));
        field("destinations", caps.cDestinations);
        put("|name ");
        wide(caps.szPname, 31);
        line_end();
        result = mixerOpen(&mixer, m, 0, 0, MIXER_OBJECTF_MIXER);
        put("mixer open");
        field("result", result);
        line_end();
        if (result != MMSYSERR_NOERROR)
            continue;
        for (d = 0; d < caps.cDestinations && d < 16; d++) {
            memset(&line, 0, sizeof(line));
            line.cbStruct = sizeof(line);
            line.dwDestination = d;
            result = mixerGetLineInfo((HMIXEROBJ)mixer, &line,
                                      MIXER_OBJECTF_HMIXER | MIXER_GETLINEINFOF_DESTINATION);
            put("line");
            field("destination", d);
            field("result", result);
            field("id", line.dwLineID);
            field("type", line.dwComponentType);
            field("sources", line.cConnections);
            field("controls", line.cControls);
            put("|name ");
            wide(line.szName, 63);
            line_end();
            if (result != MMSYSERR_NOERROR)
                continue;
            list_controls(mixer, &line);
            for (s = 0; s < line.cConnections && s < 24; s++) {
                MIXERLINE source;
                memset(&source, 0, sizeof(source));
                source.cbStruct = sizeof(source);
                source.dwDestination = d;
                source.dwSource = s;
                result = mixerGetLineInfo((HMIXEROBJ)mixer, &source,
                                          MIXER_OBJECTF_HMIXER | MIXER_GETLINEINFOF_SOURCE);
                put("source");
                field("destination", d);
                field("source", s);
                field("result", result);
                field("id", source.dwLineID);
                field("type", source.dwComponentType);
                field("controls", source.cControls);
                put("|name ");
                wide(source.szName, 63);
                line_end();
                if (result == MMSYSERR_NOERROR)
                    list_controls(mixer, &source);
            }
        }
        result = mixerClose(mixer);
        put("mixer closed");
        field("result", result);
        line_end();
    }
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    HANDLE done, watch;
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
    put("s2am-mic-v2");
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
    listen_all();
    put("end");
    line_end();
    CloseHandle(report);
    done = create(L"mic-done.txt");
    if (done != INVALID_HANDLE_VALUE)
        CloseHandle(done);
    return 0;
}
