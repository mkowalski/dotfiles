# dotfiles

Make dotfiles great again

## Documentation

https://www.chezmoi.io/

## Bootstrap

```
$ curl -sfL https://git.io/chezmoi | sh
$ chezmoi init https://github.com/mkowalski/dotfiles-chezmoi.git
$ chezmoi diff
$ chezmoi apply
```

## i3 Status Bar

```
$ git clone https://github.com/mkowalski/i3-bar.git
$ go build && mv i3-bar ~/go/bin/i3-bar
```

## SELinux and systemd troubleshooting

SELinux has the idea that binaries can be executed only from specific directories. Turns out `/home/[^/]+/\.local/bin(/.*)?` is allowed, but `/home/[^/]+/bin(/.*)?` is not. In order to fix the lock-wrapper script, the following may be needed

```
# semanage fcontext  -a -t bin_t /home/*/bin/lock-wrapper
# chcon -Rv -u system_u -t bin_t /home/*/bin/lock-wrapper
# restorecon -R -v /home/*/bin/lock-wrapper
```
