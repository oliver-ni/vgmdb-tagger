from PyInquirer import prompt
from subprocess import run
from mutagen.mp4 import MP4, MP4Tags, MP4Cover
from pathlib import Path
from tkinter import filedialog, messagebox, Button
from tkinter import ttk
import tkinter as tk
import audioread
import requests
import os

SERVER_URL = "http://vgmdb.net/cddb"
TAGS = {
    "artist": "\xa9ART",
    "aartist": "aART",
    "title": "\xa9nam",
    "album": "\xa9alb",
    "year": "\xa9day",
    "genre": "\xa9gen",
    "track": "trkn",
    "disc": "disk",
    "cover": "covr"
}

class Track(object):
    def __init__(self, number: int, offset: int, duration: int):
        self.number = number
        self.offset = offset
        self.duration = duration
    
    def duration_in_seconds(self):
        return self.duration // 75
    
    def offset_in_seconds(self):
        return self.offset // 75
    
    def __repr__(self):
        return "<Track: {}>".format(self.number)

def cddb_sum(n: int) -> int:
   r = 0
   while n:
       r, n = r + n % 10, n // 10
   return r

def cddb_discid(tracks: [Track]):
    checksum = 0
    
    for track in tracks:
        checksum += cddb_sum(track.duration_in_seconds())
    
    total = tracks[-1].offset_in_seconds() + tracks[-1].duration_in_seconds() - tracks[0].offset_in_seconds()
    
    return ((checksum % 0xff) << 24 | total << 8 | len(tracks))

def cddb_disc_info(tracks):
    disc_info = []
    disc_info.append(cddb_discid(tracks))
    disc_info.append(len(tracks))
    disc_info.extend(track.offset for track in tracks)
    disc_info.append((tracks[-1].duration + tracks[-1].offset) // 75)

    return disc_info

def convert_disc(inputfiles):
    first = min(inputfiles, key=int)
    last = max(inputfiles, key=int)
    
    print(first, last)
    
    offset = 150
    tracks = []

    for i in range(first, last + 1):
        with audioread.audio_open(str(inputfiles[i])) as f:
            t_sectors = int(f.duration * 75)
            tracks.append(Track(i, offset, t_sectors))
            offset += t_sectors

    disc_id = cddb_disc_info(tracks)
    disc_id[0] = format(disc_id[0], "x")
    disc_id = [str(x) for x in disc_id]

    query_cmd = "cddb query {}".format(" ".join(disc_id))
    query = requests.get(SERVER_URL, params={
        "cmd": query_cmd
    })

    print(query_cmd)

    if query.status_code != 200:
        return print("Error")
    
    query_lines = query.text.splitlines()
    query_status = int(query_lines[0].split(" ")[0])
    disc_category = ""

    if query_status == 200:
        category, match_id, dtitle = query_lines[0].split(" ", 3)[1:]

        question = {
            "type": "confirm",
            "name": "match",
            "message": "Found match: {}. Is this correct?".format(dtitle)
        }

        answer = prompt(question)

        if not answer["match"]:
            disc_category = "OTHER-NOT-LISTED"
        else:
            disc_category = category

    elif query_status == 210 or query_status == 211:
        question = {
            "type": "list",
            "name": "match",
            "message": "Multiple matches found, please select one",
            "choices": [
                {
                    "name": "Other (not listed)",
                    "value": "OTHER-NOT-LISTED"
                }
            ]
        }

        for i, match in enumerate(query_lines[1:-1]):
            category, match_id, dtitle = match.split(" ", 2)
            question["choices"].append({
                "name": dtitle,
                "value": category
            })
        
        answer = prompt(question)
        
        disc_category = answer["match"]
    
    if disc_category == "OTHER-NOT-LISTED" or query_status == 202:
        print("Could not find match in VGMDB CDDB.")

        question = {
            "type": "input",
            "name": "link",
            "message": "Please paste VGMDB ID, or leave blank to cancel:" 
        }
        
        answer = prompt(question)
        
        vgmdb_link = answer["link"]
        disc_category = None

    if disc_category is None:

        vgmdb = requests.get("https://vgmdb.info/album/{}".format(vgmdb_link), params={
            "format": "json"
        })

        if vgmdb.status_code != 200:
            return print("Error")
        
        info = vgmdb.json()
        
        album = info["names"]["en"]
        if " / " in album:
            artist, album = info["names"]["en"].split(" / ", 1)
        else:
            artist = info["arrangers"][0]["names"]["en"]

        if " / " in album:
            album, artist = album.split(" / ", 1)

        art_get = requests.get(info["picture_full"])

        if len(info["covers"]) > 0:
            try:
                front_cover = next(filter(lambda c: c["name"] == "Front", info["covers"]))
                art_image = requests.get(front_cover["full"])
            except:
                art_image = requests.get(info["picture_full"])
        else:
            art_image = requests.get(info["picture_full"])

        if art_image.status_code == 200:
            cover = art_image.content
        
        if len(info["discs"]) > 1:
            disc_number = int(input("Disc number:")) - 1
            sdn = "y" in input("Save disc number?")
        else:
            disc_number = 0
            sdn = False
        
        tracks = info["discs"][disc_number]["tracks"]

        for i, track in enumerate(range(first, last + 1)):
            track_name = tracks[i]["names"]["Japanese"]
            try:
                track_name = tracks[i]["names"]["Romaji"]
            except KeyError:
                pass
            try:
                track_name = tracks[i]["names"]["English"]
            except KeyError:
                pass
            converted_filename = "output/{} – {}.m4a".format(track, track_name.replace("/", ""))
            convert_cmd = [
                "ffmpeg",
                "-y",
                "-i", inputfiles[track],
                "-c:a", "alac",
                "-c:v", "copy",
                converted_filename
            ]
            run(convert_cmd)

            audio = MP4(converted_filename)
            try:
                audio.delete(filename=converted_filename)
                audio.add_tags()
            except:
                pass

            audio.tags[TAGS["title"]] = track_name
            audio.tags[TAGS["artist"]] = artist
            audio.tags[TAGS["album"]] = album
            audio.tags[TAGS["genre"]] = "Anime"
            audio.tags[TAGS["year"]] = info["release_date"].split("-", 1)[0]
            audio.tags[TAGS["track"]] = ((track, last + 1 - first),)

            if sdn:
                audio.tags[TAGS["disc"]] = ((disc_number+1, len(info["discs"])),)

            if cover is not None:
                audio.tags[TAGS["cover"]] = (MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG),)

            audio.save()
    
    else:
    
        read_cmd = "cddb read {} {}".format(disc_category, disc_id[0])
        read = requests.get(SERVER_URL, params={
            "cmd": read_cmd
        })

        if query.status_code != 200:
            return print("Error")
        
        read_lines = read.text.splitlines()
        read_status = int(read_lines[0].split(" ")[0])

        if read_status == 210:
            data = {}
            for line in read_lines[1:-1]:
                if line.startswith("#"): continue
                k, v = line.strip().split('=')
                data[k] = v

            artist, album = data["DTITLE"].split(" / ", 1)
            catalog, album = album.split(" ", 1)
            catalog = catalog[1:-1]

            if " / " in album:
                album, artist = album.split(" / ", 1)

            art_search = requests.get("https://vgmdb.info/search/albums", params={
                "format": "json",
                "q": catalog
            })

            cover = None

            if art_search.status_code == 200:
                results = art_search.json()["results"]["albums"]

                if len(results) > 0:
                    art_get = requests.get("https://vgmdb.info/{}".format(results[0]["link"]))

                    if art_get.status_code == 200:
                        try:
                            results_json = art_get.json()
                            if len(results_json["covers"]) > 0:
                                try:
                                    front_cover = next(filter(lambda c: c["name"] == "Front", results_json["covers"]))
                                    art_image = requests.get(front_cover["full"])
                                except:
                                    art_image = requests.get(info["picture_full"])
                            else:
                                art_image = requests.get(results_json["picture_full"])
                            
                            if art_image.status_code == 200:
                                cover = art_image.content
                        except:
                            pass

            for i, track in enumerate(range(first, last + 1)):
                converted_filename = "output/{} – {}.m4a".format(track, data["TTITLE{}".format(i)].replace("/", ""))
                convert_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i", inputfiles[track],
                    "-c:a", "alac",
                    "-c:v", "copy",
                    converted_filename
                ]
                run(convert_cmd)

                audio = MP4(converted_filename)
                try:
                    audio.delete(filename=converted_filename)
                    audio.add_tags()
                except:
                    pass

                audio.tags[TAGS["title"]] = data["TTITLE{}".format(i)]
                audio.tags[TAGS["artist"]] = artist
                audio.tags[TAGS["album"]] = album
                audio.tags[TAGS["genre"]] = "Anime"
                audio.tags[TAGS["year"]] = data["DYEAR"]
                audio.tags[TAGS["track"]] = ((track, last + 1 - first),)

                if cover is not None:
                    audio.tags[TAGS["cover"]] = (MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG),)

                audio.save()

if __name__ == "__main__":
    root = tk.Tk()
    root.title("VGMdb Converter")
    root.geometry("300x200")

    root.grid_columnconfigure(1, weight=1)
    root.grid_rowconfigure(1, weight=1)

    frame = ttk.Frame(root)
    frame.grid(column=1, row=1, sticky="news")

    ui = ttk.Frame(frame)
    ui.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def convert_folder():
        inputfiles = {}

        path = Path(filedialog.askdirectory())

        root.update()

        print(path.exists())

        for path in path.glob("*.flac"):
            print(os.path.basename)
            try:
                name = os.path.basename(path)
                number = int(name.split(" ")[0].replace(".", ""))
                inputfiles[number] = path
            except:
                pass
        
        print(inputfiles)
        
        convert_disc(inputfiles)

    label = ttk.Label(ui, text="VGMdb Converter")
    label.pack()

    b = ttk.Button(ui, text="Convert folder", command=convert_folder)
    b.pack()

    root.mainloop()
