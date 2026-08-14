Output assets/demo.gif
Set FontSize 14
Set Width 1200
Set Height 640
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 40ms

Type "regatlas --list-models"
Enter
Sleep 1500ms

Type "regatlas run --suite suites/toolcalling.yaml --models opus-4,opus-5 --recordings tests/fixtures"
Enter
Sleep 2500ms

Type "regatlas diff --baseline opus-4 --candidate opus-5 --out diff.json"
Enter
Sleep 1500ms

Type "regatlas report --diff diff.json"
Enter
Sleep 3500ms
