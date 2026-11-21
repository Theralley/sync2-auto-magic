# Installationsguide: CarPlay i din SYNC 2, steg för steg

*In English: [INSTALL.md](INSTALL.md).*

För dig som aldrig har gjort det här förut. Du behöver inte kunna programmera. Du behöver kunna
installera ett program på en Mac, dubbelklicka på en fil, svara på dess frågor och följa steg i
bilen. Installationsprogrammet ställer sina frågor på engelska, så menyvalen står på engelska
här också.

**Läs det här först.** Det här är en förhandsversion. Den fungerar i utvecklarens bil, en
Mondeo från 2016, och CarPlay är långsammare än i en bil som har det inbyggt.
Installationsprogrammet är provat på Mac, och den allra första installationen via
bakgrundsbilden är SyncExtPacks egen metod, som det här projektet ännu inte har kört i en bil
(testbilen hade redan SyncExtPack). Du ändrar bilens programvara på egen risk. Inget här rör den
fasta programvaran, och en ominstallation av SYNC:s egen programvara tar bort allt (se slutet av
sidan).

Räkna med en kväll: ungefär en timme vid datorn och fem till sex korta besök i bilen (ett eller
två för installationen, ett för varje förbättring).

## Ord som används

| Ord | Betydelse |
|---|---|
| **SYNC 2** / MyFord Touch | Skärmen och datorn i instrumentbrädan |
| **APIM** | Fords namn på den datorn. Dess serienummer knyter ett installationspaket till din bil |
| **SyncExtPack** | Ett tillägg från entusiaster som låter SYNC 2 köra extra appar. Projektet installerar det åt dig |
| **AutoKit** | Carlinkits app. Den visar CarPlay på skärmen när adaptern sitter i |
| **Stickan** | Ditt USB-minne. Det bär allt mellan datorn och bilen |
| **Jobb** | En liten uppgift som stickan ber bilen göra, till exempel "installera det här" eller "berätta vad du har" |
| **Mjuk omstart** | Starta om SYNC genom att hålla in ström-/volymratten och Seek-Up ⏭ i ungefär tio sekunder |

## 1. Kontrollera att bilen passar

Öppna *Settings → General → About SYNC* i bilen.

- Du behöver **SYNC 2 / MyFord Touch med pekskärmen på 8 tum**. SYNC 3 har redan CarPlay, och
  den lilla skärmen med knappar runt om är ett annat system.
- Programversionen ska vara **3.08 eller 3.10**.
- Skriv upp **APIM-serienumret**, 8 bokstäver och siffror. Du skriver in det senare.

## 2. Skaffa de tre sakerna

| Vad | Att tänka på |
|---|---|
| En **Carlinkit-adapter med sladd** av typen "AutoKit", gjord för Android-bilstereor | Till exempel [den här](https://www.amazon.se/dp/B0919JS1K3). Inte en adapter som gör sladdbunden CarPlay trådlös (2Air, U2W, Mini Ultra, 3.0/4.0/5.0): de fungerar bara i bilar som redan har CarPlay |
| Ett **USB-minne** på högst 32 GB | Det raderas om det behöver formateras. Det ska vara FAT32, vilket installationsprogrammet kontrollerar |
| En **Mac** | Linux är byggt och enhetstestat, men ännu inte provat med en riktig sticka på en Linuxdator eller i en bil: se [På Linux](#på-linux) ([#5](https://github.com/Theralley/sync2-auto-magic/issues/5)). Windows stöds inte än ([#6](https://github.com/Theralley/sync2-auto-magic/issues/6)) |

### Formatera stickan (bara om installationsprogrammet ber om det)

Stickan ska vara FAT32 med "Master Boot Record". Installationsprogrammet kontrollerar det och
raderar aldrig något själv. Om det säger att stickan inte går att använda:

1. Öppna **Skivverktyg** (tryck ⌘-mellanslag och skriv namnet).
2. Välj **Visa alla enheter** i menyn *Innehåll*.
3. Markera själva stickan, den översta raden med tillverkarens namn, inte den indragna raden
   under.
4. Klicka på **Radera**: namn `SYNC`, format **MS-DOS (FAT)**, schema **Master Boot Record**.

Allt på stickan försvinner. Kontrollera två gånger att du har valt stickan och inte en annan
skiva.

### På Linux

Nytt och ännu inte provat med en riktig sticka eller i en bil
([#5](https://github.com/Theralley/sync2-auto-magic/issues/5)). Rapporter är välkomna. Du behöver:

- Ett skrivbord som monterar USB-minnen av sig självt under `/media/<du>/` eller
  `/run/media/<du>/` (GNOME, KDE, Xfce och de flesta andra gör det).
- Python 3, util-linux 2.35 eller nyare (`lsblk`, `findmnt`; Ubuntu 22.04, Debian 11, Fedora 32
  eller senare) och udisks2 (`udisksctl`).
- [Docker Engine](https://docs.docker.com/engine/install/) med din användare i gruppen `docker`,
  eller rootless Docker. Podman är inte provat.
- En x86-64-dator, eller en ARM-dator med x86-64-emulering (Debian och Ubuntu:
  `sudo apt install qemu-user-static binfmt-support`).

Installationsprogrammet tar bara en sticka på USB-bussen, och aldrig en skiva som också bär det
system som körs (swap, `/`, `/boot`, `/home`). Formatera en sticka så här: öppna **Diskar**
(GNOME Disks), markera stickan i listan till vänster, välj *Formatera disk* i menyn med
partitionering **Kompatibel med alla system och enheter (MBR/DOS)**, och sedan **+** för att
lägga till en partition över hela stickan: namn `SYNC`, typ **För användning med alla system och
enheter (FAT)**. Namnen i menyerna kan skilja lite mellan versioner (på engelska: *Format Disk*,
*Compatible with all systems and devices (MBR / DOS)*, *For use with all systems and devices
(FAT)*). Öppna stickan en gång i filhanteraren så att den monteras. Starta
installationsprogrammet med `./install-sync2.sh` i en terminal i projektmappen; allt efter det
är som på en Mac.

## 3. Förbered datorn

1. Installera [Docker Desktop](https://www.docker.com/products/docker-desktop/) och starta det.
   Vänta tills det säger att det är igång. Det bygger installationspaketet i en avskild låda,
   så att verktyg från andra aldrig körs direkt på din Mac.
2. Ladda ner projektet: tryck på den gröna knappen **Code** på
   [projektsidan](https://github.com/Theralley/sync2-auto-magic), välj **Download ZIP** och
   packa upp filen.
3. Sätt i USB-minnet.

## 4. Kör installationsprogrammet

1. Öppna den uppackade mappen och **dubbelklicka på `Install-SYNC2.command`**. Om macOS vägrar,
   högerklicka på filen och välj *Öppna*.
2. Välj **Install CarPlay / Android Auto**.
3. Svara på frågorna: ditt APIM-serienummer, vilket USB-minne, och vad menyn *Apps* i bilen
   visar i dag. Om SyncExtPack saknas på datorn erbjuder programmet att ladda ner det.
4. Programmet bygger paketet, skriver det till stickan och kontrollerar varje fil. Första bygget
   tar några minuter.
5. Följ det programmet säger att du ska göra i bilen. Det blir en av två vägar:
   - **En bil utan extra appar (de flesta):** två besök. Först väljer du `Installer.jpg` som
     bakgrundsbild under *Settings → Display → Wallpaper → Add*, och SYNC startar om. Tillbaka
     vid datorn förbereder programmet stickan för det andra besöket, där installationen går av
     sig själv.
   - **En bil som redan har SyncExtPack** (extra appar som Reboot eller Video Player): ett
     besök. Sätt i stickan och vänta.
6. I bilen gäller alltid: motorn igång, Start-Stop avstängt, vänta tills SYNC har startat klart
   innan stickan sätts i, och låt stickan sitta kvar tills **"Install successfully completed"**
   visas.

**Så vet du att det gick bra:** *i → Apps* i bilen visar **AutoKit**, **Total Commander** och
**Reboot**, och installationsprogrammet på datorn säger "Done". Skriv `q` vid vilken fråga som
helst för att avbryta; inget går förlorat.

## 5. Första CarPlay

1. Sätt Carlinkit-adaptern i bilens USB-uttag.
2. Koppla din iPhone till adaptern med sladden.
3. Tryck **i → Apps → AutoKit**. CarPlay visas efter några sekunder.

**Så vet du att det gick bra:** CarPlays hemskärm syns på bilens skärm, den reagerar på
tryck, och musik spelas i bilens högtalare.

Lämna inte AutoKit med dess Exit-knapp ännu: gör steg 6 först, annars kan skärmen frysa (hur du
löser en frusen skärm står i slutet).

## 6. Gör CarPlay bättre: fyra förbättringar

Kör installationsprogrammet igen (dubbelklicka på `Install-SYNC2.command`) och välj
**Make CarPlay better (after the install)**. Det erbjuder fyra ändringar, frågar före var och en
och skickar dig till bilen en gång per ändring:

| Ändring | Vad du får |
|---|---|
| **Vakten** (runner guard) | När du lämnar CarPlay är SYNC tillbaka på några sekunder i stället för att skärmen fryser |
| **Mindre CarPlay-bild** | Tydligt snabbare. Bilden ligger mitt på skärmen med en svart ram |
| **Bilens mikrofon** | Siri och telefonsamtal hör dig |
| **CarPlay först** (CarPlay first) | Mycket mjukare CarPlay: det går före Fords egna skärmar när processorn är full. Fords skärmar, också bilderna från parkeringssensorer och kamera, kan reagera långsammare medan CarPlay arbetar. Provat i en bil hittills, så programmet gör det bara om du skriver `y`. Starta om SYNC en gång till efteråt; först då gäller det |

Ingen av dem kan köras medan en app från Apps-menyn är öppen, och AutoKits Exit-knapp gömmer
bara appen. Starta därför om SYNC innan varje sticka sätts i (håll in ström-/volymratten och
Seek-Up ⏭ samtidigt i ungefär tio sekunder och vänta tills SYNC är tillbaka) och öppna inte
AutoKit. Installationsprogrammet påminner dig varje gång.

**Så vet du att det gick bra:** i bilen ser du "Install successfully completed". Tillbaka vid
datorn läser programmet stickan och säger "Done: ..." för den ändringen. Om en ändring inte
kommer tillbaka som klar stannar programmet där och säger det; inget annat ändras.

<details>
<summary><b>Föredrar du Terminal? Samma jobb som kommandon</b></summary>

Gå till projektmappen (skriv `cd `, dra mappen till Terminal-fönstret, tryck Retur). Byt
`YOURSERIAL` och stickans namn mot dina.

```sh
python3 -m s2am job runner-guard --serial YOURSERIAL
python3 -m s2am job autokit-config --screen 640,384,10 --serial YOURSERIAL
python3 -m s2am job autokit-mic-gate --serial YOURSERIAL
python3 -m s2am job flash-tune --prio 253 --fast-prio 253 --serial YOURSERIAL
```

Ett jobb per besök i bilen, med SYNC omstartat och ingen app öppnad innan stickan sätts i.
Efter varje kommando skriver verktyget en rad som börjar med
`next:`. Kör den med din stickas namn, gå till bilen och läs in stickan efteråt:

```sh
python3 -m s2am stick prepare /Volumes/SYNC --job build/jobs/<id:t som skrevs ut>
python3 -m s2am stick import /Volumes/SYNC
```
</details>

### Ångra

Varje ändring kan tas tillbaka med en sticka till, från Terminal i projektmappen:

```sh
python3 -m s2am job runner-guard --off --serial YOURSERIAL            # SyncExtPacks egen startare tillbaka
python3 -m s2am job autokit-config --restore JOB_ID --serial YOURSERIAL  # bilden som den var
python3 -m s2am job autokit-patched --serial YOURSERIAL               # AutoKit utan mikrofonändringen
python3 -m s2am job flash-tune --undo --serial YOURSERIAL             # Fords skärmar först igen (starta om SYNC efteråt)
```

`JOB_ID` är det id som verktyget skrev ut när det byggde bildjobbet. Det ser ut som
`20261120-144720-akcfg-7846`, och mappen `~/.s2am/YOURSERIAL/jobs` har en fil per jobb.

## Om något går fel

- **Inget händer när stickan sätts i:** SYNC var inte redo. Dra ur den, vänta tills SYNC har
  startat klart och sätt i den igen.
- **Skärmen har frusit:** stäng av bilen, öppna och stäng förardörren och starta igen. Eller
  håll in ström-/volymratten och Seek-Up ⏭ samtidigt i ungefär tio sekunder. Inget avinstalleras
  av något av det.
- **Allt annat:** sök i [TROUBLESHOOTING.md](TROUBLESHOOTING.md) (på engelska) efter orden på
  skärmen. Varje punkt där har inträffat i en riktig bil.
- **Ta bort allt:** installera om SYNC-programvara 3.08 eller 3.10 med SyncExtPacks
  [guide för fast programvara](https://github.com/chr0m1ng/syncextpack/blob/main/FIRMWARE_INSTALLATION.md).

## Vad du kan vänta dig

CarPlay fungerar, med kartor, musik, Siri och samtal. Det är långsammare än i en modern bil,
eftersom SYNC 2:s processor avkodar bilden i programvara. Med "CarPlay först" tyckte ägaren till
den enda provade bilen att det blev mycket mjukare. I samtal hör den du pratar med ett
eko. Parkeringssensorernas ruta visas inte medan AutoKit är öppet, så lämna AutoKit innan du
backar. Det aktuella läget för allt detta står i [README](../README.md).

Om du får det att fungera, eller kör fast,
[öppna gärna ett ärende](https://github.com/Theralley/sync2-auto-magic/issues) med modell,
årsmodell och SYNC-version. Rapporter från andra bilar är det projektet behöver mest.
