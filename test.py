import ytmusicapi
import asyncio

async def main():
    api = ytmusicapi.YTMusic()
    alb = await api.get_song_album_id("8ReYQrDfo6k")
    print(alb)

if __name__ == "__main__":
    asyncio.run(main())