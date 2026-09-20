<#
.SYNOPSIS
    Reads the textual metadata chunks out of a PNG file.

.DESCRIPTION
    Walks the PNG chunk list and returns a hashtable of keyword to text
    for every tEXt, zTXt and iTXt chunk. ComfyUI uses plain tEXt with the
    keywords `prompt` and `workflow`, but other tools compress the same
    payload, so all three chunk types are handled.

    Chunk length and type are stored big-endian, which is the opposite of
    the byte order on this machine, hence the explicit reversal.

    The file is read as a stream and image data is skipped by seeking
    rather than loaded: the metadata sits in the first few kilobytes,
    while the pixels are megabytes, and these frames usually live on a
    network share.
#>
function Read-PngTextChunk {
    param(
        [Parameter(Mandatory)]
        [string] $Path
    )

    $result = @{}
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $header = New-Object byte[] 8
        if ($stream.Read($header, 0, 8) -ne 8) { throw "$Path is too short to be a PNG" }

        $signature = 137, 80, 78, 71, 13, 10, 26, 10
        for ($i = 0; $i -lt 8; $i++) {
            if ($header[$i] -ne $signature[$i]) { throw "$Path is not a PNG" }
        }

        $head = New-Object byte[] 8
        while ($stream.Read($head, 0, 8) -eq 8) {
            $lengthBytes = $head[0..3]
            [array]::Reverse($lengthBytes)
            $length = [BitConverter]::ToUInt32($lengthBytes, 0)
            $type = [System.Text.Encoding]::ASCII.GetString($head, 4, 4)

            if ($type -eq 'IEND') { break }

            if ((@('tEXt', 'zTXt', 'iTXt') -contains $type) -and $length -gt 0) {
                $data = New-Object byte[] $length
                $read = 0
                while ($read -lt $length) {
                    $got = $stream.Read($data, $read, $length - $read)
                    if ($got -le 0) { break }
                    $read += $got
                }

                $zero = [array]::IndexOf($data, [byte] 0)
                if ($zero -gt 0) {
                    $keyword = [System.Text.Encoding]::ASCII.GetString($data, 0, $zero)
                    $value = $null

                    switch ($type) {
                        'tEXt' {
                            $value = [System.Text.Encoding]::UTF8.GetString(
                                $data, $zero + 1, $data.Length - $zero - 1)
                        }
                        'zTXt' {
                            # keyword \0 compressionMethod <zlib stream>
                            $value = Expand-ZlibBytes $data[($zero + 2)..($data.Length - 1)]
                        }
                        'iTXt' {
                            # keyword \0 flag method language \0 translated \0 text
                            $flag = $data[$zero + 1]
                            $p = [array]::IndexOf($data, [byte] 0, $zero + 3) + 1
                            $p = [array]::IndexOf($data, [byte] 0, $p) + 1
                            $value = if ($flag -eq 1) {
                                Expand-ZlibBytes $data[$p..($data.Length - 1)]
                            }
                            else {
                                [System.Text.Encoding]::UTF8.GetString(
                                    $data, $p, $data.Length - $p)
                            }
                        }
                    }

                    $result[$keyword] = $value
                }

                $stream.Seek(4, [System.IO.SeekOrigin]::Current) | Out-Null   # CRC
            }
            else {
                # skip the payload and its CRC without pulling them over the wire
                $stream.Seek($length + 4, [System.IO.SeekOrigin]::Current) | Out-Null
            }
        }
    }
    finally {
        $stream.Dispose()
    }

    $result
}

<#
.SYNOPSIS
    Inflates a zlib stream into a string.

.DESCRIPTION
    DeflateStream understands the raw deflate payload but not the two
    byte zlib header in front of it, so the header is skipped here.
#>
function Expand-ZlibBytes {
    param(
        [Parameter(Mandatory)]
        [byte[]] $Data
    )

    $ms = New-Object System.IO.MemoryStream (, $Data[2..($Data.Length - 1)])
    $ds = New-Object System.IO.Compression.DeflateStream(
        $ms, [System.IO.Compression.CompressionMode]::Decompress)
    $sr = New-Object System.IO.StreamReader($ds, [System.Text.Encoding]::UTF8)
    try { $sr.ReadToEnd() } finally { $sr.Dispose(); $ds.Dispose(); $ms.Dispose() }
}
