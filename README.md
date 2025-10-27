# Secure fMP4 HLS using FFmpeg

```mermaid
flowchart LR
    A("input.mp4") --> B[/"FFmpeg"/]

    subgraph C["plain/"]
      direction LR
      C1("index.m3u8"):::file
      C2("init.mp4"):::file
      C3("indexXXX.m4s"):::file
    end

    B --> C

    subgraph D["keys/"]
      direction LR
      D1("aes.key"):::file
      D2("aes.keyinfo"):::file
    end

    C --> E[/"hls_encrypt_watcher"/]
    D --> E

    subgraph F["secure/"]
      direction LR
      F1("index.m3u8"):::file
      F2("init.mp4"):::file
      F3("indexXXX.m4s"):::file
    end

    E --> F
    D --> G[\"srv"\]
    F --> G
    G --> H[\"User"\]
```

## Run

```
export INPUTMP4=/path/to/input.mp4
docker compose up
```

- Open [hls.js demo](https://hlsjs.video-dev.org/demo/?src=http%3A%2F%2Flocalhost%3A8003%2Findex.m3u8&demoConfig=eyJlbmFibGVTdHJlYW1pbmciOnRydWUsImF1dG9SZWNvdmVyRXJyb3IiOnRydWUsInN0b3BPblN0YWxsIjpmYWxzZSwiZHVtcGZNUDQiOmZhbHNlLCJsZXZlbENhcHBpbmciOi0xLCJsaW1pdE1ldHJpY3MiOi0xfQ==) in Browser
