# KlipperScreen E3K (backup)
Copia di backup di ciò che vive in ~/KlipperScreen (fuori da questo repo):
- e3k_home.py  -> ~/KlipperScreen/addons/e3k_home.py (home a 3 colonne, spegnimento a due tocchi)
- tema ~/KlipperScreen/styles/e3k/: style.css = styles/z-bolt-noscroll/style.css + style-e3k.css;
  style.conf; images/ = symlink a ../../z-bolt/images/* + icons/*.svg sovrascritte
Attivazione in KlipperScreen.conf [main]: theme: e3k / enable_addons: True
Rollback: enable_addons: False e theme: z-bolt-noscroll (backup KlipperScreen.conf.bak-e3k-*)
