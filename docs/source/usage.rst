Usage
=======

Unauthenticated
---------------
Unauthenticated requests for retrieving playlist content or searching:

.. code-block:: python

    from ytmusicapi import YTMusic

    ytmusic = YTMusic()


If an endpoint requires authentication you will receive an error:
``Please provide authentication before using this function``

Authenticated
-------------
For authenticated requests you need to set up your credentials first: :doc:`Setup <setup/index>`

After you have created the authentication JSON, you can instantiate the class:

.. code-block:: python

    from ytmusicapi import YTMusic, OAuthCredentials
    ytmusic = YTMusic("browser.json") # or, alternatively
    ytmusic = YTMusic("oauth.json", oauth_credentials=OAuthCredentials(client_id=client_id, client_secret=client_secret)


With the :code:`ytmusic` instance you can now perform authenticated requests:

.. code-block:: python

    playlistId = await ytmusic.create_playlist("test", "test description")
    search_results = await ytmusic.search("Oasis Wonderwall")
    await ytmusic.add_playlist_items(playlistId, [search_results[0]['videoId']])

All request methods are coroutines, so they must be awaited from inside an event loop.
``YTMusic`` is also an async context manager, which closes the underlying HTTP client
on exit:

.. code-block:: python

    import asyncio
    from ytmusicapi import YTMusic

    async def main():
        async with YTMusic("browser.json") as ytmusic:
            return await ytmusic.search("Oasis Wonderwall")

    results = asyncio.run(main())

If you construct ``YTMusic`` without the context manager, call ``await ytmusic.close()``
when you are done. A client you pass in yourself via ``requests_session`` is never closed
for you.

Brand accounts
##############
To send requests as a brand account, there is no need to change authentication credentials.
Simply provide the ID of the brand account when instantiating YTMusic.
You can get the ID from https://myaccount.google.com/ after selecting your brand account
(https://myaccount.google.com/b/21_digit_number).

Example:

.. code-block:: python

    from ytmusicapi import YTMusic
    ytmusic = YTMusic("oauth.json", "101234161234936123473")


