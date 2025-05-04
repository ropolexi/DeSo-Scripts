import tkinter as tk
from tkinter import ttk
import requests
import json
import threading  # For background calculations
blacklist = ["greenwork32","globalnetwork22"]  #bots accounts username list

COMMENT_SCORE = 15
FIRST_COMMENT_SCORE = 10
REPOST_SCORE = 25
QUOTE_REPOST_SCORE = 25
FOLLOW_SCORE = 100
LIKE_SCORE = 1
POLL_SCORE = 10

like_types = ["LIKE", "LOVE", "DISLIKE", "SAD", "ASTONISHED", "ANGRY", "LAUGH"]
BASE_URL = "https://node.deso.org/api/v0/"

prof_resp="PublicKeyToProfileEntryResponse"
tpkbc ="TransactorPublicKeyBase58Check"
pkbc="PublicKeyBase58Check"

# Global variables for thread control
stop_flag = False
calculation_thread = None

def api_get(endpoint, payload=None):
    try:
        response = requests.post(BASE_URL + endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error: {e}")
        return None

def get_single_profile(Username):
    payload = {
        "NoErrorOnMissing": False,
        "PublicKeyBase58Check": "",
        "Username": Username
    }
    data = api_get("get-single-profile", payload)
    return data

def post_associations_counts(post_hash,AssociationType,AssociationValues):
    payload = {
        "AssociationType": AssociationType,
        "AssociationValues": AssociationValues,
        "PostHashHex": post_hash
    }
    data = api_get("post-associations/counts", payload)
    return data

def get_post_associations(post_hash, AssociationType,AssociationValue):
    payload = {
        "AssociationType": AssociationType,
        "AssociationValue": AssociationValue,
        "IncludeTransactorProfile": True,
        "Limit": 100,
        "PostHashHex": post_hash
    }
    data = api_get("post-associations/query", payload)
    return data


def is_following(public_key_base58_check, is_following_public_key_base58_check):
    payload = {
        "PublicKeyBase58Check": public_key_base58_check,
        "IsFollowingPublicKeyBase58Check": is_following_public_key_base58_check
    }
    data = api_get("is-following-public-key", payload)
    return data["IsFollowing"] if "IsFollowing" in data else None


def get_quote_reposts(post_hash_hex, reader):
    payload = {
        "PostHashHex": post_hash_hex,
        "Limit": 50,
        "Offset": 0,
        "ReaderPublicKeyBase58Check": reader
    }
    data = api_get("get-quote-reposts-for-post", payload)
    return data["QuoteReposts"] if "QuoteReposts" in data else None


def get_reposts(post_hash_hex, reader):
    payload = {
        "PostHashHex": post_hash_hex,
        "Limit": 50,
        "Offset": 0,
        "ReaderPublicKeyBase58Check": reader
    }
    data = api_get("get-reposts-for-post", payload)
    return data["Reclouters"] if "Reclouters" in data else None


def get_diamonds(post_hash_hex, reader):
    payload = {
        "PostHashHex": post_hash_hex,
        "Limit": 50,
        "Offset": 0,
        "ReaderPublicKeyBase58Check": reader
    }
    data = api_get("get-diamonds-for-post", payload)
    return data["DiamondSenders"] if "DiamondSenders" in data else None


def get_single_post(post_hash_hex, reader_public_key=None, fetch_parents=False, comment_offset=0, comment_limit=100, add_global_feed=False):
    payload = {
        "PostHashHex": post_hash_hex,
        "FetchParents": fetch_parents,
        "CommentOffset": comment_offset,
        "CommentLimit": comment_limit
    }
    if reader_public_key:
        payload["ReaderPublicKeyBase58Check"] = reader_public_key
    if add_global_feed:
        payload["AddGlobalFeedBool"] = add_global_feed
    data = api_get("get-single-post", payload)
    return data["PostFound"] if "PostFound" in data else None

def get_last_posts(public_key, num_to_fetch=1):
    payload = {
        "PublicKeyBase58Check": public_key,
        "NumToFetch": num_to_fetch
    }
    data = api_get("get-posts-for-public-key", payload)
    return data["Posts"] if "Posts" in data and data["Posts"] else None


def update_user_scores(username, score, user_scores):
    user_scores[username] = user_scores.get(username, 0) + score
    return user_scores

def get_first_commenter(data):
    if not data:
        return None
    user_timestamps = []
    for username, info in data.items():
        if "comment_timestamp" in info:
            user_timestamps.append((info['comment_timestamp'], username))
    user_timestamps.sort()
    return user_timestamps[0][1]

def calculate_user_category_scores(post_scores):
    user_category_scores = {}

    for post_id, user_data in post_scores.items():
        for user_id, category_scores in user_data.items():
            if user_id not in user_category_scores:
                user_category_scores[user_id] = {}

            for category, score in category_scores.items():
                if category not in user_category_scores[user_id]:
                    user_category_scores[user_id][category] = 0
                user_category_scores[user_id][category] += score

    return user_category_scores

def combine_data(post_scores, username_follow):
    combined_data = {}
    # Get all unique usernames from both dictionaries
    all_usernames = set(post_scores.keys()).union(set(username_follow.keys()))

    for username in all_usernames:
        post_score_data = post_scores.get(username, {})
        follow_score_data = username_follow.get(username, 0)

        # Calculate total score (sum of post scores and follow counts)
        filtered_data = {k: v for k, v in post_score_data.items() if k != 'comment_timestamp'}
        total_score = sum(filtered_data.values()) + follow_score_data

        if username in blacklist:
            total_score = 0
            post_score_data=0
            follow_score_data=0


        combined_data[username] = {
            'post_scores': post_score_data,
            'follow_score': follow_score_data,
            'total_score': total_score
        }

    return combined_data

def calculate_stats(user_pubkey,post_hash,output_label,NUM_POSTS_TO_FETCH):
    post_scores = {} 
    username_publickey = {}
    user_public_key = user_pubkey
    single_post_hash_check=post_hash
    output_label.config(text="Calculating...")  # Initial feedback

    if len(single_post_hash_check)>0:
        last_posts=[{"PostHashHex":single_post_hash_check,"Body":"Single","PostExtraData":{}}]
    else:
        last_posts = get_last_posts(user_public_key, NUM_POSTS_TO_FETCH)
    index=0
    if last_posts:
        for post in last_posts:
            if stop_flag:
                output_label.config(text="Calculation stopped.")
                return
            post_hash_hex = post['PostHashHex']
            output_label.config(text=f"Calculating...{str(index)}/{NUM_POSTS_TO_FETCH}")
           
            #entry2.delete("1.0", tk.END) 
            entry2.insert(tk.END, post_hash_hex)

            if post["Body"] == "":
                print("Skipping reposts")
                continue
            post_scores[post_hash_hex] = {}
            reader_public_key = user_public_key
            print("["+str(index)+"]"+post_hash_hex)
            index +=1

            print("Fetching comments...")
            single_post_details = get_single_post(post_hash_hex, reader_public_key)
            if single_post_details and single_post_details["Comments"]:
                for comment in single_post_details["Comments"]:
                    timestamp = comment["TimestampNanos"]
                    username = comment["ProfileEntryResponse"]["Username"]
                    
                    public_key = comment["ProfileEntryResponse"][pkbc]
                    username_publickey[username] = public_key
                    print(f"  Comment by: {username}")
                    body = comment["Body"]
                    print(f"  Comment : {body}")
                    post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                    post_scores[post_hash_hex][username]["comment"] = post_scores[post_hash_hex][username].get("comment", 0) + COMMENT_SCORE
                    post_scores[post_hash_hex][username]["comment_timestamp"] = timestamp

                    single_post_details_sub = get_single_post(comment["PostHashHex"], reader_public_key)
                    if single_post_details_sub and single_post_details_sub["Comments"]:
                        print("==>Sub 1 comment")
                        for comment in single_post_details_sub["Comments"]:
                            username = comment["ProfileEntryResponse"]["Username"]
                            public_key = comment["ProfileEntryResponse"][pkbc]
                            username_publickey[username] = public_key
                            print(f"    Comment by: {username}")
                            body = comment["Body"]
                            print(f"    Comment : {body}")
                            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                            post_scores[post_hash_hex][username]["comment"] = post_scores[post_hash_hex][username].get("comment", 0) + COMMENT_SCORE

                            single_post_details_sub2 = get_single_post(comment["PostHashHex"], reader_public_key)
                            if single_post_details_sub2 and single_post_details_sub2["Comments"]:
                                print("==>Sub 2 comment")
                                for comment in single_post_details_sub2["Comments"]:
                                    username = comment["ProfileEntryResponse"]["Username"]
                                    public_key = comment["ProfileEntryResponse"][pkbc]
                                    username_publickey[username] = public_key
                                    print(f"        Comment by: {username}")
                                    body = comment["Body"]
                                    print(f"        Comment : {body}")
                                    post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                                    post_scores[post_hash_hex][username]["comment"] = post_scores[post_hash_hex][username].get("comment", 0) + COMMENT_SCORE

            
            first_commenter = get_first_commenter(post_scores[post_hash_hex])
            print(f'first_commenter:{first_commenter}')
            if first_commenter is not None:
                post_scores[post_hash_hex][first_commenter]["comment"] = post_scores[post_hash_hex][first_commenter].get("comment", 0) + FIRST_COMMENT_SCORE

            if diamond_sender_details := get_diamonds(post_hash_hex, user_public_key):
                for sender in diamond_sender_details:
                    username = sender["DiamondSenderProfile"]["Username"]
                    public_key = sender["DiamondSenderProfile"][pkbc]
                    username_publickey[username] = public_key
                    diamond_level_score = pow(10, sender["DiamondLevel"] - 1)
                    print("  Lvl " + str(sender["DiamondLevel"])+ f" Diamond  sent by: {username}")
                    post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                    post_scores[post_hash_hex][username]["diamond"] = post_scores[post_hash_hex][username].get("diamond", 0) + diamond_level_score

            if repost_details := get_reposts(post_hash_hex, user_public_key):
            
                for user in repost_details:
                    username = user["Username"]
                    print(f"  Reposted by: {username}")
                    post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                    post_scores[post_hash_hex][username]["repost"] = post_scores[post_hash_hex][username].get("repost", 0) + REPOST_SCORE

            if quote_repost_details := get_quote_reposts(post_hash_hex, user_public_key):
                
                for user in quote_repost_details:
                    username = user["ProfileEntryResponse"]["Username"]
                    print(f"  Quote reposted by: {username}")
                    post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                    post_scores[post_hash_hex][username]["quote_repost"] = post_scores[post_hash_hex][username].get("quote_repost", 0) + QUOTE_REPOST_SCORE


            like_summary = post_associations_counts(post_hash_hex,"REACTION",like_types)
            if like_summary["Total"]>0:
                for like_type in like_summary["Counts"]:
                    if like_summary["Counts"][like_type]>0:
                            data = get_post_associations(post_hash_hex,"REACTION", like_type)
                            if data and "Associations" in data:
                                for record in data["Associations"]:
                                    if data[prof_resp][record[tpkbc]] is not None:
                                        username = data[prof_resp][record[tpkbc]]["Username"]
                                        public_key = data[prof_resp][record[tpkbc]][pkbc]
                                        username_publickey[username] = public_key
                                        print(f"  {like_type} by: {username}")
                                        post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                                        post_scores[post_hash_hex][username][f"{like_type}"] = post_scores[post_hash_hex][username].get(f"{like_type}", 0) + LIKE_SCORE

            if "PollOptions" in post["PostExtraData"]:
                poll_summary = post_associations_counts(post_hash_hex,"POLL_RESPONSE",json.loads(post["PostExtraData"]["PollOptions"]))
                if poll_summary["Total"]>0:
                    for poll_type in poll_summary["Counts"]:
                        if poll_summary["Counts"][poll_type]>0:
                            data = get_post_associations(post_hash_hex, "POLL_RESPONSE",poll_type)
                            if data and "Associations" in data:
                                for record in data["Associations"]:
                                    if data[prof_resp][record[tpkbc]] is not None:
                                        username = data[prof_resp][record[tpkbc]]["Username"]
                                        public_key = data[prof_resp][record[tpkbc]][pkbc]
                                        username_publickey[username] = public_key
                                        print(f"  {poll_type} by: {username}")
                                        post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                                        post_scores[post_hash_hex][username]["POLL"] = post_scores[post_hash_hex][username].get("POLL", 0) + POLL_SCORE


    user_scores1 = calculate_user_category_scores(post_scores)

    username_follow={}
    for username in user_scores1:
        public_key = username_publickey.get(username)
        isFollowing = is_following(public_key, user_public_key) if public_key else False
        follow_score = FOLLOW_SCORE if isFollowing else 0
        username_follow[username] = follow_score

    print("User Post data:") 
    print(user_scores1)

    print("username_follow:")
    print(username_follow)

    # Combine the data
    combined_data = combine_data(user_scores1, username_follow)

    sorted_data = sorted(combined_data.items(), key=lambda item: item[1]['total_score'], reverse=True)
    top_10 = sorted_data[:10]
    output_label.config(text="Done")
    root = tk.Tk()
    
    root.title("Deso Stats Table")
    column_widths = {
        "Username": 100,  # Adjust as needed
        "comment": 30,
        "diamond": 30,
        "repost": 30,
        "quote_repost": 30,
        "LIKE": 30,
        "LOVE": 30,
        "DISLIKE": 30,
        "SAD": 30,
        "ASTONISHED": 30,
        "ANGRY": 30,
        "LAUGH": 30,
        "poll": 30,
        "Follow Score": 30,
        "Total Score": 40
    }

    tree = ttk.Treeview(root, columns=list(column_widths.keys()), show="headings")

    for col, width in column_widths.items():
        tree.heading(col, text=col)
        tree.column(col, width=width)

    tree.heading("Username", text="👤")
    tree.heading("comment", text="💬")
    tree.heading("diamond", text="💎")
    tree.heading("repost", text="🔁")
    tree.heading("quote_repost", text="📢")
    tree.heading("LIKE", text="👍")
    tree.heading("LOVE", text="❤️")
    tree.heading("DISLIKE", text="👎")
    tree.heading("SAD", text="😥")
    tree.heading("ASTONISHED", text="😮")
    tree.heading("ANGRY", text="😠")
    tree.heading("LAUGH", text="😂")
    tree.heading("poll", text="📊")
    tree.heading("Follow Score", text="➕")
    tree.heading("Total Score", text="💯")

    for username, info in top_10:
        tree.insert("", "end", 
                    values=(username, 
                            info['post_scores'].get('comment',''), 
                            info['post_scores'].get('diamond',''), 
                            info['post_scores'].get('repost',''), 
                            info['post_scores'].get('quote_repost',''), 
                            info['post_scores'].get('LIKE',''), 
                            info['post_scores'].get('LOVE',''), 
                            info['post_scores'].get('DISLIKE',''), 
                            info['post_scores'].get('SAD',''), 
                            info['post_scores'].get('ASTONISHED',''), 
                            info['post_scores'].get('ANGRY',''), 
                            info['post_scores'].get('LAUGH',''), 
                            info['post_scores'].get('POLL',''), 
                            info['follow_score'], 
                            info['total_score']))

    tree.pack(pady=10)

    root.mainloop()



def button_click():
    global calculation_thread,stop_flag
    try:
        stop_flag = False  # Reset stop flag
        if calculation_thread and calculation_thread.is_alive():
            output_label.config(text="Existing calculation is running.")
            return
        
        user = entry1.get()
        if len(user) != 55:
            user_data = get_single_profile(user)
            user_pub_key = user_data["Profile"]["PublicKeyBase58Check"]
        else:
            user_pub_key = user
        post_hash = entry2.get()
        
        if len(post_hash)>0:
            NUM_POSTS_TO_FETCH=1
        else:
            NUM_POSTS_TO_FETCH = int(entry3.get())
        calculation_thread = threading.Thread(target=calculate_stats, args=(user_pub_key, post_hash, output_label,NUM_POSTS_TO_FETCH))
        calculation_thread.start()
     
    except Exception as e:
        output_label.config(text=f"Error: {e}")  # Display error if something goes wrong

def stop_calculation():
    global stop_flag
    stop_flag = True
    output_label.config(text="Stopping calculation...")

root = tk.Tk()
root.title("Deso Stats Calculator")

label1 = ttk.Label(root, text="User Public Key or Username:")
label1.grid(row=0, column=0, sticky="w", padx=5, pady=5)
entry1 = ttk.Entry(root, width=70)
entry1.grid(row=0, column=1, padx=5, pady=5)

label2 = ttk.Label(root, text="Post ID (Single post Stats):")
label2.grid(row=1, column=0, sticky="w", padx=5, pady=5)
entry2 = ttk.Entry(root, width=70)
entry2.grid(row=1, column=1, padx=5, pady=5)

label3 = ttk.Label(root, text="How many posts to check:")
label3.grid(row=2, column=0, sticky="w", padx=5, pady=5)
entry3 = ttk.Entry(root, width=70)
entry3.grid(row=2, column=1, padx=5, pady=5)

calculate_button = ttk.Button(root, text="Calculate", command=button_click)
calculate_button.grid(row=3, column=0, columnspan=1, pady=10)

stop_button = ttk.Button(root, text="Stop", command=stop_calculation)
stop_button.grid(row=3, column=1, columnspan=1, pady=10)


output_label = ttk.Label(root, text="")
output_label.grid(row=4, column=0, columnspan=2, pady=5)

label1 = ttk.Label(root, text="Instructions:\nTo check for last number of posts information \n1. Enter User Public Key or username\n2. Enter How many posts to check\n\nTo check specific post information\n1. Enter User Public Key or username\n2. Enter Post ID")
label1.grid(row=5, column=0, columnspan=2,sticky="w", padx=5, pady=5)

root.mainloop()


