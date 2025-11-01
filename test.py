import ytmusicapi
import asyncio


async def main() -> None:
    api = ytmusicapi.YTMusic()
    alb = await api.get_song_album_id("8ReYQrDfo6k")
    print(alb)

    sl = await api.get_album_songs_clean("MPREb_4zrNr6aRmzK")
    print(sl)

    sl2 = await api.get_album_songs_clean(alb)
    print(sl2)


if __name__ == "__main__":
    asyncio.run(main())

# FINDINGS!
# from album id ->
# send browse request with album ID
# get canonical URL (contains proper playlist ID)
# from playlist ID -> browse request with VL + playlist ID
# get any song you want WITH NO MUSIC VIDEOS OR OTHER FLUFF!!