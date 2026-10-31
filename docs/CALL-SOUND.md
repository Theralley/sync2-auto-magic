# Call sound: narrowband or wideband?

Rasmus: calls in the car sound boxy, with no bass. The likely cause is narrowband Bluetooth
calls: hands-free (HFP) with the CVSD codec, sampled at 8 kHz, which carries the old telephone
band, about 300 to 3400 Hz. Wideband calls (HFP 1.6 with mSBC, 16 kHz) carry about 50 to
7000 Hz and sound much fuller. Which one a call uses is agreed between SYNC's Bluetooth stack
(in its read-only system image) and the phone, at the start of each call.

Two read-only ways to find out. Neither changes anything in the car.

## 1. The iPhone's Bluetooth log (this decides it)

1. On the Mac, sign in at [Apple's Profiles and Logs page](https://developer.apple.com/bug-reporting/profiles-and-logs/)
   (a free Apple account is enough) and download the **Bluetooth** logging profile for iOS.
2. Send it to the iPhone (AirDrop), then Settings, *Profile Downloaded*, Install. Restart the
   iPhone.
3. In the car: a call of about a minute **through SYNC** (Bluetooth, not CarPlay), with both
   sides talking.
4. Right after it, take a sysdiagnose: hold both volume buttons and the side button for about
   a second, until a short vibration. Wait about ten minutes.
5. Settings, Privacy & Security, Analytics & Improvements, Analytics Data:
   `sysdiagnose_...`, AirDrop it to the Mac.
6. On the Mac, unpack it; the Bluetooth log is a `.pklg` file under `logs/Bluetooth/`. Then:

   ```sh
   python3 tools/hfp_codec.py path/to/the.pklg
   ```

   It prints the car's hands-free features (whether it can negotiate a codec at all), the
   codecs the car offers and the one the phone picked, how each audio link was set up, and a
   verdict: **NARROWBAND** (CVSD) or **WIDEBAND** (mSBC).
7. Afterwards remove the profile: Settings, General, VPN & Device Management.

A sysdiagnose holds a great deal of personal data. Keep it on the Mac, outside every
repository, and delete it when done. `hfp_codec.py` prints no addresses, numbers or names.

## 2. SYNC's own settings

```sh
python3 -m s2am job registry --serial YOURSERIAL
```

A read-only job: `s2amreg.exe` copies the registry's Bluetooth, call, audio and other
settings (`HKLM\Software`, `Comm`, `Drivers`, `Audio`, `System` and `HKCU`, six levels down) to
`registry.txt` on the stick. It never writes to the registry. A value is not copied, only its
size, when its name or its key's path looks like a secret (a paired phone's link key, PINs,
passwords), and no binary value longer than 8 bytes is copied, whatever it is called (a link
key is 16 bytes). The job waits for it at most 90 seconds, and does not read again if a run
cut short had already finished the copy. The import prints how many keys and values came back.

## What the answer means

| The log says | Then |
|---|---|
| Wideband (mSBC) | The codec is not the cause; look at the microphone and SYNC's own call audio processing |
| Narrowband, and the car offers only CVSD (no codec negotiation in its AT+BRSF) | SYNC 2's Bluetooth stack does not do wideband. It sits in SYNC's read-only system image, so s2am cannot change it. The way round is CarPlay through the adapter: there the call audio travels in CarPlay instead (to test when the adapter is here) |
| Narrowband, although the car offers mSBC | The phone chose CVSD; worth a second call, and a look at the registry for a wideband setting |
