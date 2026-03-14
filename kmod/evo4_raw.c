// SPDX-License-Identifier: GPL-2.0+
/*
 * evo4_raw — raw USB control transfer access for Audient EVO4
 *
 * This module binds to the EVO4 USB device and exposes /dev/evo4 as a misc
 * device. A single ioctl (EVO4_CTRL_TRANSFER) lets userspace send/receive
 * arbitrary USB control transfers via the kernel's usb_control_msg(), which
 * bypasses usbfs interface-ownership checks. snd-usb-audio continues to
 * handle audio streaming and standard ALSA mixer controls undisturbed.
 *
 * Use case: controlling Mixer Unit 60 (hardware monitor mix) and other
 * vendor-specific Extension Units not exposed by snd-usb-audio.
 */

#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/uaccess.h>
#include <linux/usb.h>

#define AUDIENT_VID 0x2708
#define EVO4_PID 0x0006

#define EVO4_MAX_DATA 256

/* ioctl payload — matches the struct userspace packs */
struct evo4_ctrl_xfer {
  __u8 bRequestType;
  __u8 bRequest;
  __u16 wValue;
  __u16 wIndex;
  __u16 wLength;
  __u8 data[EVO4_MAX_DATA];
};

/* ioctl number: type='E' (0x45), nr=0, read+write, size of struct */
#define EVO4_CTRL_TRANSFER _IOWR('E', 0, struct evo4_ctrl_xfer)

struct evo4_device {
  struct usb_device *udev;
  struct miscdevice misc;
};

/* We store the single device pointer — EVO4 is a unique device */
static struct evo4_device *evo4_dev;
static DEFINE_MUTEX(evo4_lock);

static long evo4_ioctl(struct file *file, unsigned int cmd, unsigned long arg) {
  struct evo4_ctrl_xfer xfer;
  unsigned int pipe;
  void *dmabuf;
  int ret;

  if (cmd != EVO4_CTRL_TRANSFER)
    return -ENOTTY;

  if (copy_from_user(&xfer, (void __user *)arg, sizeof(xfer)))
    return -EFAULT;

  if (xfer.wLength > EVO4_MAX_DATA)
    return -EINVAL;

  /* usb_control_msg requires a DMA-able buffer, not stack memory */
  dmabuf = kmalloc(xfer.wLength, GFP_KERNEL);
  if (!dmabuf)
    return -ENOMEM;

  /* For OUT transfers, copy data into the DMA buffer */
  if (!(xfer.bRequestType & USB_DIR_IN))
    memcpy(dmabuf, xfer.data, xfer.wLength);

  mutex_lock(&evo4_lock);

  if (!evo4_dev || !evo4_dev->udev) {
    mutex_unlock(&evo4_lock);
    kfree(dmabuf);
    return -ENODEV;
  }

  /* Build the correct pipe based on transfer direction */
  if (xfer.bRequestType & USB_DIR_IN)
    pipe = usb_rcvctrlpipe(evo4_dev->udev, 0);
  else
    pipe = usb_sndctrlpipe(evo4_dev->udev, 0);

  ret = usb_control_msg(evo4_dev->udev, pipe, xfer.bRequest, xfer.bRequestType,
                        xfer.wValue, xfer.wIndex, dmabuf, xfer.wLength,
                        1000 /* 1s timeout */);

  mutex_unlock(&evo4_lock);

  if (ret < 0) {
    kfree(dmabuf);
    return ret;
  }

  /* For IN transfers, copy the response data back to userspace */
  if (xfer.bRequestType & USB_DIR_IN) {
    memcpy(xfer.data, dmabuf, ret);
    xfer.wLength = ret;
    if (copy_to_user((void __user *)arg, &xfer, sizeof(xfer))) {
      kfree(dmabuf);
      return -EFAULT;
    }
  }

  kfree(dmabuf);
  return ret;
}

static const struct file_operations evo4_fops = {
    .owner = THIS_MODULE,
    .unlocked_ioctl = evo4_ioctl,
};

static int evo4_probe(struct usb_interface *intf,
                      const struct usb_device_id *id) {
  struct usb_device *udev = interface_to_usbdev(intf);

  /*
   * snd-usb-audio claims interfaces 0-2 (audio control + streaming).
   * Interface 3 (DFU) is left unbound — we grab it just to get the
   * usb_device handle. We don't actually use interface 3 for anything;
   * all our work goes through endpoint 0 (control pipe).
   */
  if (intf->cur_altsetting->desc.bInterfaceNumber != 3)
    return -ENODEV;

  evo4_dev = kzalloc(sizeof(*evo4_dev), GFP_KERNEL);
  if (!evo4_dev)
    return -ENOMEM;

  evo4_dev->udev = usb_get_dev(udev);
  evo4_dev->misc.minor = MISC_DYNAMIC_MINOR;
  evo4_dev->misc.name = "evo4";
  evo4_dev->misc.fops = &evo4_fops;

  if (misc_register(&evo4_dev->misc)) {
    dev_err(&intf->dev, "failed to register /dev/evo4\n");
    usb_put_dev(evo4_dev->udev);
    kfree(evo4_dev);
    evo4_dev = NULL;
    return -ENODEV;
  }

  dev_info(&intf->dev, "Audient EVO4 raw control registered at /dev/evo4\n");
  usb_set_intfdata(intf, evo4_dev);
  return 0;
}

static void evo4_disconnect(struct usb_interface *intf) {
  struct evo4_device *dev = usb_get_intfdata(intf);

  if (!dev)
    return;

  mutex_lock(&evo4_lock);
  misc_deregister(&dev->misc);
  usb_put_dev(dev->udev);
  dev->udev = NULL;
  evo4_dev = NULL;
  mutex_unlock(&evo4_lock);

  kfree(dev);
  dev_info(&intf->dev, "Audient EVO4 raw control disconnected\n");
}

static const struct usb_device_id evo4_id_table[] = {
    {USB_DEVICE(AUDIENT_VID, EVO4_PID)}, {}};
MODULE_DEVICE_TABLE(usb, evo4_id_table);

static struct usb_driver evo4_driver = {
    .name = "evo4_raw",
    .id_table = evo4_id_table,
    .probe = evo4_probe,
    .disconnect = evo4_disconnect,
};
module_usb_driver(evo4_driver);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("audient-evo-py contributors");
MODULE_DESCRIPTION("Raw USB control transfer access for Audient EVO4");
