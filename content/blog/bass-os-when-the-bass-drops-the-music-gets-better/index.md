---
title: "Bass OS - when the bass drops, the music gets better"
date: 2024-03-13T12:32:00+05:00
description: "Project Update for Bass OS (Bliss Bass) and what it means"
tags: ["startup", "business", "AOSP", "Android", "entrepreneurship", "development", "products", "Bass OS", "TheBlissfulEntrepreneur"]
image: cover.png
aliases: ["/blog/Bass-OS-when-the-bass-drops-the-music-gets-better/"]
---

## Project Background

About a year ago, I was contacted by a number of companies that wanted their own Android for PC OS that they could control the access and redistribution rights to. So I started on a journey putting together a new form of Bliss OS for the same kind of devices but done a little differently in order to target businesses, and product use, but was put together in a way that would allow me to retain rights to the parts that apply to all devices (the generic bits). When I first got started, the goal was to make one source have as many features as possible without the use of proprietary components like Google Play Store, Widevine, etc., and then just enable/disable various features and options for specific use cases. Around April of 2023, that goal was achieved and I had a solid starting point for the source that opened up many of the tiny little changes required for device and application specific use, and brought it all together with a single build toolkit. This at least set the stage for the bare minimum needs, and shed light on the future challenges for the project.


## Challenges

The project updates would have to have the following goals, and those had a few challenges attached: 


* **Make that system easy to expand**: \
I used a system that allows developers a simple method for expanding on the available build options and configuring the source all from the command line. Learning lessons from my previous projects like Android-Generic Project, I also wanted to include a way to make things easily upgradeable to new versions of Android. So this system had to include some of the advances to the patching system used in AG. 
* **Make the system build process accessible for others**: \
I expanded the Bliss OS source and created new tools that greatly simplify the process and provide the majority of the configuration options through a single interface. This allows developers to easily setup, configure and deploy their generic Android .iso's with little effort.
* **Reserve a place for private patches, addons, etc. for companies**:  \
Some companies and developers aren't able to share things as open source, so I need to take that into account and provide a way for them to naturally separate what should be a generic change and what should be a private change. So I added a few places for companies to add their changes and have them automatically apply when the source unfolds. 
* **Reserve a place for the most valued assets to easily be integrated into the system**: \
I have many changes that don't really fit in the “generic device” category, like password protected admin access, kernel level changes to guard against unwanted wireless devices being plugged in, etc., so I wanted to still offer these specialized changes to companies that had a need for them. The way I do this is through licensing addons (features). Each addon will come as its own separate project that gets linked inside the main bass-os project folder as an addon, patchset or manifest. This covers prebuilt pro versions of our apk's, sources for API's and packages, and individual changes to be placed on-top of the source. 

Looking at what the community and industry have put together for Raspberry-Pi builds on Glodroid, Glodroid-Community and Tesla-Android, I was able to take inspiration from how they have things setup, and apply those concepts to Bass OS. This resulted in a single repo setup that developers and clients can easily manage, while retaining the ability to separate our private addons and features, and give developers a way to include their private changes as Ill. All while automating the process down to just a few keystrokes. 

For those that are curious, I detail a little about the toolkit on our Website for Bass OS ([https://bliss-bass.blisscolabs.dev](https://bliss-bass.blisscolabs.dev)), along with a glimpse of the many use-cases and applications for using an OS put together like this. 


## Licensing

The largest challenge I had for this project was related to ego. How do I create a product that is as easy to adopt and maintain as an Open-Source project, while still retaining the ability to generate income from it? This is where the licensing system comes into play. For many of the parts of this system, there are addons and features available. For the build system, we include the base “generic” options and scripts as part of the open-source project, while we reserve the “value added” bits for licensed use. And any parts of those two sides that cross over, should have a warning or error attached when they are used without licensing access to the change first.

Taking this approach will still allow us to provide companies, hobbyists, and individuals a free to use set of features, apps, and configurations, while attempting to force licensing onto those that would want to change the source and rebrand without properly licensing. Because innovation through open-source is only viable when we all play by the rules. 


## Sources & Documentation

Now we can get to the exciting part of this post, the source code. You can find the source at the following link: [https://github.com/Bliss-Bass/bass-os](https://github.com/Bliss-Bass/bass-os) but please pay close attention to the readme for that repo, as it contains all the required information to get things up and rolling. Including dependencies, hardware requirements, resource links and more.

I plan on creating addon guides & templates, contributing guides, and linking the various feature guides we have on Bliss OS docs that they have adopted for some of their builds. This should allow the community everything they need to build off our open-source offerings and set their own terms for licensing their creations if they choose to do so.


## Gratitude

I do want to say Thank You to all the members of the business and user community that have helped the growth of this project. And I am looking forward to 2024 being a great year for Android on x86 based hardware. 
