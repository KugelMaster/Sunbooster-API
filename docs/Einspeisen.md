Einspeisen funktioniert so:

Bei 200W werden bspw. diese Bytes geschickt:
```
AA AA 00 09 38 00 17 00 13 01 0A 00 03
```

`AA AA 00 09` ist immer gleich, egal bei welcher Anfrage man schaut. Es muss also der Header sein. \
`38` scheint eine Art Message-Counter zu sein. Diese zählt für Anfragen um 1 hoch (aber nicht immer?) \
`00 17` ist auch eine Art Zähler. Diese zählt jede Anfrage um 1 hoch. \
`00 13 01 0A` ist dann wahrscheinlich die Gerät-ID. \
`00 03` bestimmt dann den Payload, was das Gerät machen soll (hier: 200W einspeisen).

Die Auswahl in der App folgt folgender Skala:
-   0W -> \x00
- 100W -> \x01
- 150W -> \x02
- 200W -> \x03
- 250W -> \x04
- 300W -> \x05
- ...
- 750W -> \x0e
- 800W -> \x0f

-> Alle 50W Bytes um 1 hochzählen (50W wird übersprungen)
