"""Customer-facing wording for every seed help article (used by build_seed_data.py).

One customer step per agent step, in the same order and with the same facts: no new promises, prices or timeframes.
Agent steps say what the support desk does; customer steps say what the customer can do or what we will do for them.
"""
CUSTOMER_STEPS = {
    "KB-001": [
        "Make sure mobile data is turned on and airplane mode is off.",
        "Check that your phone shows signal bars.",
        "Check in your self-care account that you still have data left on your plan.",
        "Restart your phone and try mobile data again.",
        "If data still doesn't work, tell me your phone model, where you are and when it stopped, and our team will take it from there.",
    ],
    "KB-002": [
        "Check your signal, and whether the slowdown happens everywhere or only in certain places.",
        "Restart your phone and try again.",
        "If it's still slow, note when and where it happens and let me know so our team can look into it.",
    ],
    "KB-003": [
        "Check your signal strength where the calls drop.",
        "If you can, try calling from a different location.",
        "Restart your phone.",
        "If calls keep dropping, note when they drop and how often, and let me know so our team can investigate.",
    ],
    "KB-004": [
        "Check your signal strength during the affected calls.",
        "Make another call to see if the problem happens again.",
        "Restart your phone.",
        "Let me know whether the problem affects calls you make, calls you receive, or both.",
    ],
    "KB-005": [
        "Restart your phone.",
        "Check that your SIM card is inserted properly.",
        "See whether the signal comes back after the restart.",
        "If there's still no signal, tell me where you are and your phone model, and our team will investigate.",
    ],
    "KB-006": [
        "Restart your phone.",
        "Check that your phone has signal.",
        "Send a test message to another number.",
        "Let me know whether the problem is with messages you receive, messages you send, or both.",
    ],
    "KB-007": [
        "Make sure roaming is turned on for your line.",
        "Restart your phone.",
        "Let your phone search for and connect to a local network again.",
        "If roaming still doesn't work, tell me which country you're in and our team will look into it.",
    ],
    "KB-008": [
        "Check that both your phone and your plan support 5G.",
        "Check the network mode selected in your phone's settings.",
        "Restart your phone.",
        "If 5G still doesn't appear, let me know which network mode your phone shows.",
    ],
    "KB-009": [
        "Restart your router (and your fibre box, if you have one).",
        "Test your connection again.",
        "If you can, compare the speed on a few different devices.",
        "If it's still slow, note when it happens and let me know so our team can look into it.",
    ],
    "KB-010": [
        "Check the status lights on your router and fibre box.",
        "Restart your router and fibre box.",
        "Watch whether the connection drops again.",
        "If the drops continue, note when they happen and let me know so our team can investigate.",
    ],
    "KB-011": [
        "Check the status lights on your router and fibre box, and make sure all cables are firmly connected.",
        "Restart your router and fibre box.",
        "Try going online from a second device.",
        "If there's still no internet, tell me what the status lights show and our team will take it from there.",
    ],
    "KB-012": [
        "Make sure Wi-Fi is turned on on your device.",
        "Restart your router.",
        "If you can, try connecting from another device.",
        "Let me know whether the problem affects all your devices or just one.",
    ],
    "KB-013": [
        "Make sure your router and fibre box have fully finished restarting.",
        "Check the connection status and that all cables are firmly connected.",
        "Try using the service again.",
        "If it still isn't working, tell me what the status lights show and our team will investigate.",
    ],
    "KB-014": [
        "Find the reference number for your connection request.",
        "Share it here so we can check your installation status.",
        "If the status can't be confirmed, one of our team will follow up with you.",
    ],
    "KB-015": [
        "Check the status of your activation request.",
        "Make sure any activation step you were asked to complete is done.",
        "If the service still isn't active, let me know and one of our team will follow up.",
    ],
    "KB-016": [
        "Double-check the account ID you're signing in with.",
        "Try signing in again.",
        "If you still can't sign in, use the account recovery option on the sign-in page.",
    ],
    "KB-017": [
        "Use the password reset option on the sign-in page.",
        "Complete the verification step you're asked to do.",
        "If you can't complete the reset, let me know and our account team will help.",
    ],
    "KB-018": [
        "Update your details in your account profile.",
        "Check that your changes have saved.",
        "If a detail can't be changed there, let me know and one of our team will update it for you.",
    ],
    "KB-019": [
        "Look through the details on your bill.",
        "Find the charge you want to dispute.",
        "Note the billing period and why you think the charge is wrong.",
        "Send us these details here to raise a dispute, and our billing team will review it.",
    ],
    "KB-020": [
        "Find the charge on your bill and check which billing period it covers.",
        "Compare it with the activity shown in your account.",
        "If the charge still doesn't make sense, let me know and our billing team will review it.",
    ],
    "KB-021": [
        "Check the payment status in your account.",
        "Check whether any money was taken for the failed payment.",
        "If needed, try the payment again through your account.",
        "If the payment still fails, let me know and our payments team will look into it.",
    ],
    "KB-022": [
        "Find your refund reference and the details of the original payment.",
        "Check the refund status in your account.",
        "If the status isn't clear, let me know and our billing team will check it.",
    ],
    "KB-023": [
        "Check your current plan and choose the plan you'd like to move to.",
        "Check in your account whether you can switch to that plan.",
        "If you're eligible, submit the plan change.",
    ],
    "KB-024": [
        "I can share the details of the plans currently available.",
        "Tell me which plan you'd like to look at more closely.",
    ],
    "KB-025": [
        "Check the status of your recharge payment.",
        "Check whether your balance has updated.",
        "If the recharge still hasn't gone through, let me know and our team will review the payment.",
    ],
    "KB-026": [
        "Check that your SIM activation request has been submitted.",
        "Complete the activation steps you were given.",
        "Restart your phone after activation if you're asked to.",
    ],
    "KB-027": [
        "We'll first check that your account is eligible for a replacement SIM or eSIM.",
        "If it is, we'll create the replacement request for you.",
    ],
    "KB-028": [
        "Turn off your phone.",
        "If your phone has a removable SIM, take it out and put it back in carefully.",
        "Turn your phone back on and check whether the SIM is detected.",
        "If the SIM still isn't detected, let me know and our team will help.",
    ],
    "KB-029": [
        "For your safety, please don't share passwords, PINs or codes in this chat.",
        "We'll secure your account using our account-security process.",
        "Tell us about any activity you don't recognise so our team can review it.",
    ],
    "KB-030": [
        "We'll check for any reported outage on your service in your area.",
        "We'll only share outage information that has been confirmed.",
        "If there's no confirmed outage, our team will investigate further.",
    ],
    "KB-031": [
        "Note the exact times the drops happen over a few days.",
        "Check whether the lights on your router or fibre box change when the connection drops.",
        "If you can, check whether a device connected by cable drops at the same time as your Wi-Fi devices.",
        "If you've already restarted your router, there's no need to do it again.",
        "Share the times you noted here, and our team will arrange a line test.",
    ],
    "KB-032": [
        "Find both charges on your bill and note their dates and descriptions.",
        "Check whether the two charges are for the same billing period.",
        "Note the reference number of each payment.",
        "Send us these details here to raise a duplicate-charge dispute.",
    ],
    "KB-033": [
        "Check whether the problem happens close to the router as well as further away.",
        "Restart your router.",
        "Try a second device in the same spot.",
        "Let me know which rooms and devices are affected so our team can look into it.",
    ],
    "KB-034": [
        "For your safety, we won't discuss account details in chat, and please don't share any.",
        "We'll secure your account straight away using our account-security process.",
        "Our security team is being alerted now. Please tell us when you first noticed the problem.",
    ],
    "KB-035": [
        "Make sure roaming is turned on for your line, before or after you travel.",
        "If you need mobile data abroad, turn on data roaming in your phone's settings.",
        "Restart your phone so it connects to a local network.",
        "If it still doesn't connect, tell me which country you're in and the network name your phone shows.",
    ],
    "KB-036": [
        "Check that your phone model supports 5G.",
        "Check that your plan includes 5G.",
        "Make sure your phone's preferred network mode includes 5G.",
        "If 5G still doesn't show, let me know where you are and the network mode your phone shows.",
    ],
    "KB-037": [
        "Check that your phone model and software version support the feature.",
        "Make sure the feature is turned on in your phone's settings.",
        "Check that your plan includes the feature.",
        "Restart your phone and try the feature again.",
        "If it still doesn't work, tell me your phone model, software version and any message you see.",
    ],
    "KB-038": [
        "Check whether the problem affects one device or every device on your home network.",
        "Restart your router (and fibre box, if you have one) and the affected device.",
        "Check the feature's setting in your router or self-care account, if it has one.",
        "If it still isn't working, tell me the device type, when it fails and any message you see.",
    ],
    "KB-039": [
        "Check whether the problem affects calls or messages you make, ones you receive, or both.",
        "Try a different number to see whether the problem only happens with one number.",
        "Restart your phone and try again.",
        "If it still isn't working, tell me roughly when it happens and any message you hear, and our team will investigate.",
    ],
    "KB-040": [
        "Check which device and which line or eSIM profile are affected.",
        "Make sure the line or eSIM profile shows as active on the device.",
        "Restart both the device and any phone it's paired with.",
        "If it still isn't working, tell me the device model, the profile status and any message you see.",
    ],
    "KB-041": [
        "Tell me which bill, payment or account item you're asking about.",
        "We'll review it using your account records.",
        "We'll explain exactly what your account shows.",
        "If it can't be explained, our billing or account team will look into it.",
    ],
    "KB-042": [
        "We'll first verify your account.",
        "We'll issue a new eSIM profile for your new phone.",
        "Install the new profile on your phone, then restart it.",
    ],
}
