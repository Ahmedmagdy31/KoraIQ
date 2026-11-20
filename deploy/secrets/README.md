Put the Firebase service-account key here as `firebase.json` (never commit it).
Firebase console -> Project settings -> Service accounts -> Generate new private key.
Then: chmod 444 firebase.json   (the API container runs as a non-root user and must be able to read it)
