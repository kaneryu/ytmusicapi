import ytmusicapi
import asyncio

artists = ['coldplay', 'michael jackson', 'dr dre', 'imagine dragons', 'taylor swift', 'eminem', 'adele', 'ed sheeran']

async def main() -> None:
    ytm = ytmusicapi.YTMusic()
    async with ytm._session:
        results = await asyncio.gather(*[ytm.search(artist, filter="songs", limit=1) for artist in artists])
        print(*[f"{result[0]['artists'][0]['name']}: {result[0]['title']}" for result in results], sep="\n")
        
        # get_user = await ytm.get_user("UCDyuTkFC49GDHC_nUviOEag")
        # results = await ytm.get_user_videos("UCDyuTkFC49GDHC_nUviOEag", get_user["videos"]["params"])
        # print("User Videos:")
        # print(results)
        
        search = await ytm.search("Imagine Dragons", filter="songs", limit=5)
        print("Search Results:")
        print(*[f"{song['artists'][0]['name']}: {song['title']}" for song in search], sep="\n")

asyncio.run(main())