#!/bin/bash
# Runs as root inside a fresh cloud-image VM. Turns it into the desktop the guide assumes:
#   xubuntu: Ubuntu 26.04 + Xubuntu desktop      mint: Ubuntu 24.04 + Linux Mint 22.3 "Zena" Xfce packages
#   arch:    Arch Linux + Xfce
# Ends with LightDM auto-logging in user "tester" to an Xfce session. Nothing here touches Nix.
set -euxo pipefail
D=$1
cloud-init status --wait || true

autologin() {   # $1 = session name
  mkdir -p /etc/lightdm/lightdm.conf.d
  printf '[Seat:*]\nautologin-user=tester\nautologin-user-timeout=0\nautologin-session=%s\nuser-session=%s\n' "$1" "$1" \
    > /etc/lightdm/lightdm.conf.d/90-autologin.conf
}

case $D in
xubuntu|mint)
  export DEBIAN_FRONTEND=noninteractive
  # cloud images start unattended upgrades on first boot; stop them so they don't hold the apt lock
  systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
  systemctl stop apt-daily.service apt-daily-upgrade.service 2>/dev/null || true
  while fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1; do sleep 3; done
  if [ "$D" = mint ]; then
    echo 'deb http://packages.linuxmint.com zena main upstream import backport' \
      > /etc/apt/sources.list.d/official-package-repositories.list
    # same pin Mint itself ships
    printf 'Package: *\nPin: origin packages.linuxmint.com\nPin-Priority: 700\n' \
      > /etc/apt/preferences.d/official-package-repositories.pref
    apt-get -o Acquire::AllowInsecureRepositories=true update || true
    apt-get install -y --allow-unauthenticated linuxmint-keyring
    apt-get update
    # Mint ships without snapd (its ubuntu-system-adjustments package installs the nosnap pin itself)
    apt-get purge -y snapd 2>/dev/null || true
    DPKG="-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confnew"
    apt-get install -y $DPKG mint-meta-xfce
    # Mint's base-files (os-release says "Linux Mint") is older-versioned than Ubuntu's: allow the downgrade
    v=$(apt-cache madison base-files | awk '/packages.linuxmint.com/{print $3; exit}')
    [ -n "$v" ] && apt-get install -y $DPKG --allow-downgrades "base-files=$v" || true
    rm -f /etc/xdg/autostart/mintwelcome.desktop
    S=xfce
  else
    apt-get update
    apt-get install -y xubuntu-core || apt-get install -y xubuntu-desktop-minimal
    S=xubuntu; [ -f /usr/share/xsessions/xubuntu.desktop ] || S=xfce
  fi
  apt-get install -y lightdm xfce4-terminal
  echo /usr/sbin/lightdm > /etc/X11/default-display-manager
  ;;
arch)
  pacman -Syu --noconfirm --needed xorg-server xfce4 xfce4-terminal lightdm lightdm-gtk-greeter
  groupadd -rf autologin
  gpasswd -a tester autologin
  systemctl enable lightdm
  S=xfce
  ;;
esac

autologin "$S"
systemctl set-default graphical.target
# no lock screen / screensaver popping up over the screenshots
rm -f /etc/xdg/autostart/light-locker.desktop /etc/xdg/autostart/xfce4-screensaver.desktop
# skip vanilla Xfce's "first start of the panel" dialog: start from the default panel layout
install -d -o tester -g tester /home/tester/.config/xfce4/xfconf/xfce-perchannel-xml
[ -f /etc/xdg/xfce4/panel/default.xml ] && install -o tester -g tester /etc/xdg/xfce4/panel/default.xml \
  /home/tester/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
chown -R tester:tester /home/tester/.config
. /etc/os-release; echo "PROVISIONED: $PRETTY_NAME, session $S"
cat /etc/linuxmint/info 2>/dev/null || true
