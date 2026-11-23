The goal of the overlayFS system here is :
- When the use runs a command , it creates a directorie with the folder that have been created in it : this is the lower dir , it cannot be modfied it only in RO mode.
- If we want to write somthing we have another folder called upper-dir where we write what we wants and we see the overlay of the two folders , we can only modify the upper dir

So the concept is that for a commande like:
STEPS:
    - Command1
    - Command2
    ....
    - CommandN

We have an overlayFS with this parameters:

lower_dir = upperN + upperN-1 .... + upper1 + rootfs 
upper_dir = new_folder

At each step of a build the upper_step becomes a lower_dir for the next layer.

So what we want is to save theses frozen layers to let any image reuse them instead of recreating them each time we build an image.b