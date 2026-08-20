import asyncio
from urllib.parse import urlparse

import pytest

from ytmusicapi.exceptions import YTMusicUserError


class TestLibrary:
    async def test_get_library_playlists(self, config, yt_oauth, yt_empty):
        playlists = await yt_oauth.get_library_playlists(50)
        assert len(playlists) > 25

        playlists = await yt_oauth.get_library_playlists(None)
        assert len(playlists) >= config.getint("limits", "library_playlists")

        playlists = await yt_empty.get_library_playlists()
        assert len(playlists) <= 1  # "Episodes saved for later"

    async def test_get_library_songs(self, config, yt_oauth, yt_empty):
        with pytest.raises(YTMusicUserError):
            await yt_oauth.get_library_songs(None, True)
        songs = await yt_oauth.get_library_songs(100)
        assert len(songs) >= 100
        songs = await yt_oauth.get_library_songs(200, validate_responses=True)
        assert len(songs) >= config.getint("limits", "library_songs")
        songs = await yt_oauth.get_library_songs(order="a_to_z")
        assert len(songs) >= 25
        songs = await yt_empty.get_library_songs()
        assert len(songs) == 0

    async def test_get_library_albums_invalid_order(self, yt):
        with pytest.raises(YTMusicUserError):
            await yt.get_library_albums(100, order="invalid")

    async def test_get_library_albums(self, yt_oauth, yt_brand, yt_empty):
        albums = await yt_oauth.get_library_albums(100)
        assert len(albums) > 50
        for album in albums:
            assert "playlistId" in album
        albums = await yt_brand.get_library_albums(100, order="a_to_z")
        assert len(albums) > 50
        albums = await yt_brand.get_library_albums(100, order="z_to_a")
        assert len(albums) > 50
        albums = await yt_brand.get_library_albums(100, order="recently_added")
        assert len(albums) > 50
        albums = await yt_empty.get_library_albums()
        assert len(albums) == 0

    async def test_get_library_artists(self, config, yt_auth, yt_oauth, yt_brand, yt_empty):
        artists = await yt_auth.get_library_artists(50)
        assert len(artists) > 40
        artists = await yt_oauth.get_library_artists(order="a_to_z", limit=50)
        assert len(artists) > 40
        artists = await yt_brand.get_library_artists(limit=None)
        assert len(artists) > config.getint("limits", "library_artists")
        artists = await yt_empty.get_library_artists()
        assert len(artists) == 0

    async def test_get_library_subscriptions(self, config, yt_brand, yt_empty):
        artists = await yt_brand.get_library_subscriptions(50)
        assert len(artists) > 40
        artists = await yt_brand.get_library_subscriptions(order="z_to_a")
        assert len(artists) > 20
        artists = await yt_brand.get_library_subscriptions(limit=None)
        assert len(artists) > config.getint("limits", "library_subscriptions")
        artists = await yt_empty.get_library_subscriptions()
        assert len(artists) == 0

    async def test_get_library_podcasts(self, yt_brand, yt_empty):
        podcasts = await yt_brand.get_library_podcasts(limit=50, order="a_to_z")
        assert len(podcasts) > 25

        empty = await yt_empty.get_library_podcasts()
        assert len(empty) == 1  # saved episodes playlist is always there

    async def test_get_library_channels(self, yt_brand, yt_empty):
        channels = await yt_brand.get_library_channels(limit=50, order="recently_added")
        assert len(channels) > 25

        empty = await yt_empty.get_library_channels()
        assert len(empty) == 0

    async def test_get_liked_songs(self, yt_brand, yt_empty):
        songs = await yt_brand.get_liked_songs(200)
        assert len(songs["tracks"]) > 100
        songs = await yt_empty.get_liked_songs()
        assert songs["trackCount"] == 0

    async def test_get_saved_episodes(self, yt_brand, yt_empty):
        episodes = await yt_brand.get_saved_episodes(200)
        assert len(episodes["tracks"]) > 0
        episodes = await yt_empty.get_saved_episodes()
        assert episodes["trackCount"] == 0

    @pytest.mark.xdist_group("history")
    async def test_get_history(self, yt_oauth):
        songs = await yt_oauth.get_history()
        assert len(songs) > 0
        assert all(song["feedbackToken"] is not None for song in songs)
        assert all(
            song["listenAgainFeedbackTokens"] is not None
            for song in songs
            if "listenAgainFeedbackTokens" in song
        )

    @pytest.mark.xdist_group("history")
    async def test_manipulate_history_items(self, yt_auth, sample_video):
        song = await yt_auth.get_song(sample_video)
        response = await yt_auth.add_history_item(song)
        assert response.status_code == 204
        songs = await yt_auth.get_history()
        assert len(songs) > 0
        response = await yt_auth.remove_history_items([songs[0]["feedbackToken"]])
        assert "feedbackResponses" in response

    async def test_rate_song(self, yt_auth, sample_video):
        response = await yt_auth.rate_song(sample_video, "LIKE")
        assert "actions" in response
        response = await yt_auth.rate_song(sample_video, "DISLIKE")
        assert "actions" in response
        response = await yt_auth.rate_song(sample_video, "INDIFFERENT")
        assert response
        with pytest.raises(YTMusicUserError):
            await yt_auth.rate_song(sample_video, "notexist")

    async def test_edit_song_library_status(self, yt_brand, sample_album):
        album = await yt_brand.get_album(sample_album)
        response = await yt_brand.edit_song_library_status(album["tracks"][0]["feedbackTokens"]["add"])
        album = await yt_brand.get_album(sample_album)
        assert album["tracks"][0]["inLibrary"]
        assert response["feedbackResponses"][0]["isProcessed"]
        response = await yt_brand.edit_song_library_status(album["tracks"][0]["feedbackTokens"]["remove"])
        album = await yt_brand.get_album(sample_album)
        assert not album["tracks"][0]["inLibrary"]
        assert response["feedbackResponses"][0]["isProcessed"]

    @pytest.mark.skip(reason="2026-02: Unpin from Listen Again is broken in YTM")
    async def test_listen_again_feedback_tokens(self, yt_brand):
        sample_album = "MPREb_4pL8gzRtw1p"
        track_index = 1  # test with an audio track for the sake of free accounts (music video pin state isn't reflected in the corresponding song menu)

        async def test_pin_token(token_key: str, expected_status: bool):
            album = await yt_brand.get_album(sample_album)
            token = album["tracks"][track_index]["listenAgainFeedbackTokens"][token_key]

            response = await yt_brand.edit_song_library_status(token)
            assert response["feedbackResponses"][0]["isProcessed"]

            for attempt in range(5):
                await asyncio.sleep(1.5)  # wait for the pin state to change
                album = await yt_brand.get_album(sample_album)
                if album["tracks"][track_index]["pinnedToListenAgain"] == expected_status:
                    return

            raise AssertionError(f"pinnedToListenAgain didn't change to {expected_status}")

        await test_pin_token("pin", True)
        await test_pin_token("unpin", False)

    async def test_rate_playlist(self, yt_auth):
        response = await yt_auth.rate_playlist("OLAK5uy_l3g4WcHZsEx_QuEDZzWEiyFzZl6pL0xZ4", "LIKE")
        assert "actions" in response
        response = await yt_auth.rate_playlist("OLAK5uy_l3g4WcHZsEx_QuEDZzWEiyFzZl6pL0xZ4", "INDIFFERENT")
        assert "actions" in response

    async def test_subscribe_artists(self, yt_auth):
        with pytest.warns(DeprecationWarning):
            await yt_auth.subscribe_artists(["UCUDVBtnOQi4c7E8jebpjc9Q"])
        await yt_auth.subscribe_artist("UCUDVBtnOQi4c7E8jebpjc9Q")
        await yt_auth.unsubscribe_artists(["UCUDVBtnOQi4c7E8jebpjc9Q"])

    async def test_subscribe_artists_rejects_multiple(self, yt_auth):
        with pytest.raises(YTMusicUserError, match="only supports subscribing to one artist"):
            await yt_auth.subscribe_artists(["UC1", "UC2"])

    async def test_get_account_info(self, config, yt, yt_oauth):
        with pytest.raises(Exception, match="Please provide authentication"):
            await yt.get_account_info()

        account_info = await yt_oauth.get_account_info()
        assert account_info["accountName"] == config.get("auth", "account_name")
        assert account_info["channelHandle"] == config.get("auth", "channel_handle")
        assert bool(urlparse(account_info["accountPhotoUrl"]))
