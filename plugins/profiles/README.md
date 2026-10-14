# Chip profiles

Each file describes one chip family. The Schematic Review uses it to check power pins,
boot/strapping pins, reset, crystal and debug access.

* `match`: regular expressions tested against the symbol part name and the value.
* `pins`: profile pin name -> list of regular expressions for the symbol pin name
  (upper case, without `_`, spaces or `~{}`; a pin named `GPIO18/USB_D-` matches `GPIO18` or `USBD-`).
* `rules`: see `schreview.py` for the rule types (`supply`, `decoupling`, `bulk`, `strap`,
  `max_cap`, `min_cap`, `enable_rc`, `crystal`, `tie_ground`, `same_net`, `no_float`, `boot_pin`,
  `series_r`, `debug`). `tier` is `block`, `risk` or `cosmetic`.
* `source` and `verified`: the datasheet or design guide the values come from, and the date.

Put your own profiles in a `kicad_review_profiles` folder in the project; a profile with the same
`id` replaces the bundled one. Please send corrections with the datasheet section.
