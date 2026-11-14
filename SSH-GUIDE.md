# Connecting to a Kobo over SSH (firmware 4.46, no KOReader or mods)

*[Versión en español más abajo](#español)*

Kobo's firmware ships with an OpenSSH server that is disabled by default. You turn it on with a file; you don't need to install anything.
Tested on a Kobo Clara BW running 4.46.23852. Other models or versions may not have this option.

## 1. Enable SSH

1. Connect the Kobo to your computer over USB.
2. Show hidden files and open the Kobo's `.kobo` folder.
3. Look for a file named `ssh-disabled`. It's a short text file with instructions. If it isn't there, your firmware doesn't offer this option.
4. Rename it to `ssh-enabled`, with no extension.
5. Eject the Kobo, unplug it, and **restart it** (power off, then on). Putting it to sleep isn't enough.

## 2. Find the Kobo's IP address

On the Kobo, go to *More → Settings → Device information → IP address*. Wi-Fi must be on.
Kobo turns Wi-Fi off after a few idle minutes, even while charging. If it stops responding, tap **Sync** to reconnect it.

## 3. First login: set the password

On your computer (Windows 10/11, macOS and Linux all include `ssh`):

```bash
ssh root@KOBO_IP
```

- The first time, it asks whether you trust the host. Type `yes`.
- You get in without a password and see *"Welcome, please set your password"*. Type a new password twice. Nothing appears on screen while you type.
- You then get a `[root@kobo ~]#` prompt. Type `exit` to leave.

From then on, every login asks for that password.

> **Important:** don't cut the connection while it's asking for the password, whether by closing the window, pressing Ctrl+C, or using a tool that connects without a keyboard. Kobo's script then keeps re-running `passwd` forever, using about 90 % of the CPU and draining the battery, until you reboot the Kobo.

## 4. Good to know

- Kobo forces every `root` login through its welcome script (`ForceCommand` in `/etc/ssh/sshd_config`). As a result:
  - `ssh root@IP some-command` does **not** run the command. Use the interactive prompt instead.
  - `scp` and `sftp` do **not** work.
- To move files, use the Kobo's user storage (`/mnt/onboard`, the drive you see over USB) as a go-between.
- The system partition (`/`) is writable. A mistake there can leave the Kobo unable to boot, so back up before changing anything.

## 5. Example: copy `libnickel` out for the patch

In the Kobo's SSH prompt:

```sh
cp /usr/local/Kobo/libnickel.so.1.0.0 /mnt/onboard/
md5sum /mnt/onboard/libnickel.so.1.0.0
sync
exit
```

Connect over USB and copy `libnickel.so.1.0.0` from the root of the Kobo drive to your computer. You can delete it from the Kobo afterwards.
Copies over USB can arrive corrupted with some cables. `make_patch.py` checks the file's hash and refuses to continue if it's wrong; if that happens, try another cable or port.

## 6. Install a `KoboRoot.tgz`

Copy `KoboRoot.tgz` into the Kobo's `.kobo` folder and reboot. On boot, Kobo checks that the archive is intact (`gunzip -t`) before installing it, and deletes it when it's done. To confirm it was installed, run this over SSH:

```sh
md5sum /usr/local/Kobo/libnickel.so.1.0.0
```

Compare the result with the "Patched MD5" that `make_patch.py` printed.

## 7. Log in without a password (optional, with a key)

On your computer:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/kobo
```

Copy the contents of `~/.ssh/kobo.pub`, which is a single line. Then, in the Kobo's prompt:

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'PASTE_THE_LINE_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

From then on:

```bash
ssh -i ~/.ssh/kobo root@KOBO_IP
```

## 8. Disable SSH

Rename `.kobo/ssh-enabled` back to `ssh-disabled` and reboot.
This is recommended when you're not using it: SSH gives full `root` access to the Kobo to anyone on your network who knows the password.

---

# Español

El firmware de Kobo trae un servidor OpenSSH desactivado de fábrica. Se activa con un archivo; no hace falta instalar nada.
Probado en un Kobo Clara BW con la versión 4.46.23852. Otros modelos o versiones pueden no tener esta opción.

## 1. Activar el SSH

1. Conecta el Kobo al ordenador por USB.
2. Muestra los archivos ocultos y abre la carpeta `.kobo` del Kobo.
3. Busca el archivo `ssh-disabled`. Es un texto corto con instrucciones. Si no existe, tu firmware no ofrece esta opción.
4. Cámbiale el nombre a `ssh-enabled`, sin extensión.
5. Expulsa el Kobo, desconéctalo y **reinícialo** (apágalo y vuelve a encenderlo). Suspenderlo no basta.

## 2. Averiguar la IP del Kobo

En el Kobo, ve a *Más → Ajustes → Información del dispositivo → Dirección IP*. El WiFi tiene que estar encendido.
Kobo apaga el WiFi a los pocos minutos sin usarlo, aunque esté enchufado. Si deja de responder, pulsa **Sincronizar** para que se vuelva a conectar.

## 3. Primera conexión: crear la contraseña

En el ordenador (Windows 10/11, macOS y Linux ya traen `ssh`):

```bash
ssh root@IP_DEL_KOBO
```

- La primera vez te pregunta si confías en el equipo. Escribe `yes`.
- Entras sin contraseña y aparece *"Welcome, please set your password"*. Escribe la contraseña nueva dos veces. No se ve nada en pantalla mientras escribes.
- Después aparece la consola `[root@kobo ~]#`. Escribe `exit` para salir.

A partir de entonces, cada conexión pide esa contraseña.

> **Importante:** no cortes la conexión mientras pide la contraseña, ni cerrando la ventana, ni con Ctrl+C, ni con un programa que se conecte sin teclado. Si lo haces, el script de Kobo se queda repitiendo `passwd` sin parar, con el procesador a alrededor del 90 % y gastando batería, hasta que reinicies el Kobo.

## 4. Lo que conviene saber

- Kobo obliga a que todas las conexiones de `root` pasen por su script de bienvenida (`ForceCommand` en `/etc/ssh/sshd_config`). Por eso:
  - `ssh root@IP comando` **no** ejecuta el comando. Usa la consola interactiva.
  - `scp` y `sftp` **no** funcionan.
- Para pasar archivos, usa la memoria del Kobo (`/mnt/onboard`, la unidad que ves por USB) como intermediaria.
- La partición del sistema (`/`) se puede escribir. Un error ahí puede dejar el Kobo sin arrancar, así que haz una copia de seguridad antes de tocar nada.

## 5. Ejemplo: sacar `libnickel` para el parche

En la consola SSH del Kobo:

```sh
cp /usr/local/Kobo/libnickel.so.1.0.0 /mnt/onboard/
md5sum /mnt/onboard/libnickel.so.1.0.0
sync
exit
```

Conecta el Kobo por USB y copia `libnickel.so.1.0.0` de la raíz de la unidad del Kobo al ordenador. Después puedes borrarlo del Kobo.
Con algunos cables, las copias por USB pueden llegar dañadas. `make_patch.py` comprueba la huella del archivo y no sigue si no es correcta; en ese caso, prueba con otro cable u otro puerto.

## 6. Instalar un `KoboRoot.tgz`

Copia `KoboRoot.tgz` a la carpeta `.kobo` del Kobo y reinícialo. Al arrancar, Kobo comprueba que el archivo esté íntegro (`gunzip -t`) antes de instalarlo, y lo borra al terminar. Para confirmar que se ha instalado, ejecuta por SSH:

```sh
md5sum /usr/local/Kobo/libnickel.so.1.0.0
```

Compara el resultado con el «Patched MD5» que mostró `make_patch.py`.

## 7. Entrar sin contraseña (opcional, con una llave)

En el ordenador:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/kobo
```

Copia el contenido de `~/.ssh/kobo.pub`, que es una sola línea. Después, en la consola del Kobo:

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'PEGA_AQUI_LA_LINEA' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

A partir de entonces:

```bash
ssh -i ~/.ssh/kobo root@IP_DEL_KOBO
```

## 8. Desactivar el SSH

Vuelve a cambiar el nombre de `.kobo/ssh-enabled` a `ssh-disabled` y reinicia.
Es recomendable cuando no lo uses: el SSH da acceso total (`root`) al Kobo a cualquiera de tu red que sepa la contraseña.
