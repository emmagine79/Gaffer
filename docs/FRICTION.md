# Friction log

Every comment Captain made while testing Gaffer, kept so we can come back to each one. Add new ones to the bottom. Mark an item **Fixed** with the PR when it ships.

Testing started on 18 Oct 2026, about 03:30 local.

| # | When | What Captain said | What was behind it | Status |
|---|------|-------------------|--------------------|--------|
| 1 | 18 Oct, 03:30 | "I've opened the Gaffer app that I could find in my apps, but when I click on the individual lights, nothing happens." | `~/Applications/Gaffer.app` was still the scan-only proof build from SPEC-001. Nothing replaced it when the real app was built, and nothing told him it was out of date. | Worked around: new build installed by hand. Open: an old Gaffer should not sit in Applications looking current. |
| 2 | 18 Oct, 03:40 | "When I want to add the Godox lights, it's asking me to import keys. I thought this was supposed to be automatic." | His lights were paired to another app, so they show under "Paired with something else". The add sheet leads with **Import keys** and says little about the other route: reset the light, then Pair. | Open |
| 3 | 18 Oct, 03:45 | "I actually don't even have the Godox app in the first place." | Import keys only helps someone who has the Godox app on an iPhone. For everyone else the sheet should lead with **Reset and pair**. | Open |
| 4 | 18 Oct, 03:50 | "Can you look up how I can reset my LA150Bi and SL60IID lights?" | Gaffer's help says only "hold the light's reset button until it flashes". Godox lights reset with the **Bluetooth** button: hold it about 2 seconds until the Bluetooth icon flashes. The sheet should give the steps for each model. | Open |
| 5 | 18 Oct, 04:00 | "I have a Molus G200 but it's showing as SL60IID." | The Zhiyun MOLUS G200 uses the same Bluetooth mesh service as Godox lights. Its maker bytes read as Godox model `0039` (SL60IID), and the Godox reader ran before the Zhiyun one. | **Fixed** in branch `claude/molus-not-godox`: a name that a Zhiyun model file claims is never read as Godox. |
