import tkinter as tk
from tkinter import ttk
import requests
import json
import threading  # For background calculations
import concurrent.futures
import csv
import datetime

blacklist = ["greenwork32","globalnetwork22"]  #bots accounts username list

COMMENT_SCORE = 15
FIRST_COMMENT_SCORE = 10
REPOST_SCORE = 25
QUOTE_REPOST_SCORE = 25
FOLLOW_SCORE = 100
LIKE_SCORE = 1
POLL_SCORE = 10

backround_colour = "#00a86b"
foreground = "white"

like_types = ["LIKE", "LOVE", "DISLIKE", "SAD", "ASTONISHED", "ANGRY", "LAUGH"]
BASE_URL = "https://node.deso.org/api/v0/"

prof_resp="PublicKeyToProfileEntryResponse"
tpkbc ="TransactorPublicKeyBase58Check"
pkbc="PublicKeyBase58Check"

# Global variables for thread control
stop_flag = True
calculation_thread = None


def api_get(endpoint, payload=None):
    try:
        response = requests.post(BASE_URL + endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error: {e}")
        return None

def get_single_profile(Username,PublicKeyBase58Check=""):
    payload = {
        "NoErrorOnMissing": False,
        "PublicKeyBase58Check": PublicKeyBase58Check,
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

def get_first_commenter(post_scores,post_hash_hex):
    if not post_scores[post_hash_hex]:
        return None
    user_timestamps = []
    for username, info in post_scores[post_hash_hex].items():
        if "comment_timestamp" in info:
            user_timestamps.append((info['comment_timestamp'], username))
    user_timestamps.sort()
    first_commenter=user_timestamps[0][1]

    print(f'first_commenter:{first_commenter}')
    if first_commenter is not None:
        post_scores[post_hash_hex][first_commenter]["comment"] = post_scores[post_hash_hex][first_commenter].get("comment", 0) + FIRST_COMMENT_SCORE
    

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

def update_comments(post_comments_body,post_hash_hex,reader_public_key,username_publickey,post_scores,info):
    print("Fetching comments...")
    result_steps.config(text="Fetching comments...")
    single_post_details = get_single_post(post_hash_hex, reader_public_key)
    #print(single_post_details)
    post_comments_body[post_hash_hex]["post"] = single_post_details["Body"]
    if single_post_details and single_post_details["Comments"]:
        comment_index=1
        for comment in single_post_details["Comments"]:
            comments_size = len(single_post_details["Comments"])
            result_steps.config(text=f"Fetching comments...({comment_index}/{comments_size})")
            comment_index +=1
            timestamp = comment["TimestampNanos"]
            username = comment["ProfileEntryResponse"]["Username"]
            
            public_key = comment["ProfileEntryResponse"][pkbc]
            username_publickey[username] = public_key
            print(f"  Comment by: {username}")
            body = comment["Body"]
            info["comments_count"] = info.get("comments_count",0) + 1
            print(f"  Comment : {body}")
            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
            
            post_comments_body[post_hash_hex]["comments"][username]={}
            post_scores[post_hash_hex][username]["comment"] = post_scores[post_hash_hex][username].get("comment", 0) + COMMENT_SCORE
            post_scores[post_hash_hex][username]["comment_timestamp"] = timestamp
            post_comments_body[post_hash_hex]["comments"][username] = body
            
            single_post_details_sub = get_single_post(comment["PostHashHex"], reader_public_key)
            if single_post_details_sub and single_post_details_sub["Comments"]:
                print("==>Sub 1 comment")
                for comment in single_post_details_sub["Comments"]:
                    username = comment["ProfileEntryResponse"]["Username"]
                    public_key = comment["ProfileEntryResponse"][pkbc]
                    username_publickey[username] = public_key
                    print(f"    Comment by: {username}")
                    body = comment["Body"]
                    info["comments_count"] = info.get("comments_count",0) + 1
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
                            info["comments_count"] = info.get("comments_count",0) + 1
                            print(f"        Comment : {body}")
                            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                            post_scores[post_hash_hex][username]["comment"] = post_scores[post_hash_hex][username].get("comment", 0) + COMMENT_SCORE
        get_first_commenter(post_scores,post_hash_hex)
        print(info)
def update_diamonds(post_hash_hex,user_public_key,username_publickey,post_scores,info):
    result_steps.config(text="Fetching diamonds...")
            
    if diamond_sender_details := get_diamonds(post_hash_hex, user_public_key):
        diamond_index=1
        for sender in diamond_sender_details:
            diamond_size=len(diamond_sender_details)
            result_steps.config(text=f"Fetching diamonds...({diamond_index}/{diamond_size})")
            diamond_index +=1
            username = sender["DiamondSenderProfile"]["Username"]
            public_key = sender["DiamondSenderProfile"][pkbc]
            username_publickey[username] = public_key
            diamond_level_score = pow(10, sender["DiamondLevel"] - 1)
            print("  Lvl " + str(sender["DiamondLevel"])+ f" Diamond  sent by: {username}")
            if sender["DiamondLevel"]==1:
                info["diamonds_lvl1_count"] = info.get("diamonds_lvl1_count",0) + 1
            if sender["DiamondLevel"]==2:
                info["diamonds_lvl2_count"] = info.get("diamonds_lvl2_count",0) + 1
            if sender["DiamondLevel"]==3:
                info["diamonds_lvl3_count"] = info.get("diamonds_lvl3_count",0) + 1
            if sender["DiamondLevel"]==4:
                info["diamonds_lvl4_count"] = info.get("diamonds_lvl4_count",0) + 1
            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
            post_scores[post_hash_hex][username]["diamond"] = post_scores[post_hash_hex][username].get("diamond", 0) + diamond_level_score     
    
    #focus diamonds - focus diamond lvl 1 mean diamondapp diamond lvl 2
    diamond_summary = post_associations_counts(post_hash_hex,"DIAMOND",[])
    if diamond_summary["Total"]>0:
        for like_type in diamond_summary["Counts"]:
            if diamond_summary["Counts"][like_type]>0:
                    data = get_post_associations(post_hash_hex,"DIAMOND", like_type)
                    if data and "Associations" in data:
                        for record in data["Associations"]:
                            user_data = get_single_profile("",record["ExtraData"]["SenderPublicKey"])
                            username = user_data["Profile"]["Username"]
                            level=int(record["ExtraData"]["Level"])+1
                            diamond_level_score = pow(10, level - 1)
                            print(f"  Lvl {level} Diamond  sent by: {username}")
                            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                            post_scores[post_hash_hex][username]["diamond"] = post_scores[post_hash_hex][username].get("diamond", 0) + diamond_level_score
         

def update_reposts(post_hash_hex,user_public_key,post_scores,info):
    result_steps.config(text="Fetching reposts...")
    if repost_details := get_reposts(post_hash_hex, user_public_key):
        repost_index=1
        for user in repost_details:
            repost_size= len(repost_details)
            result_steps.config(text=f"Fetching reposts...({repost_index}/{repost_size})")
            repost_index +=1
            info["reposts_count"] = info.get("reposts_count",0) + 1
            username = user["Username"]
            print(f"  Reposted by: {username}")
            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
            post_scores[post_hash_hex][username]["repost"] = post_scores[post_hash_hex][username].get("repost", 0) + REPOST_SCORE
            
def update_quote_reposts(post_hash_hex,user_public_key,post_scores,info):
    result_steps.config(text="Fetching quote reposts...")
    if quote_repost_details := get_quote_reposts(post_hash_hex, user_public_key):
        quote_repost_index = 1
        for user in quote_repost_details:
            quote_repost_size= len(quote_repost_details)
            result_steps.config(text=f"Fetching quote reposts...({quote_repost_index}/{quote_repost_size})")
            quote_repost_index +=1
            info["quote_reposts_count"] = info.get("quote_reposts_count",0) + 1
            username = user["ProfileEntryResponse"]["Username"]
            print(f"  Quote reposted by: {username}")
            post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
            post_scores[post_hash_hex][username]["quote_repost"] = post_scores[post_hash_hex][username].get("quote_repost", 0) + QUOTE_REPOST_SCORE
            
def update_reactions(post_hash_hex,username_publickey,post_scores,info):
    result_steps.config(text="Fetching reactions...")
    like_summary = post_associations_counts(post_hash_hex,"REACTION",like_types)
    if like_summary["Total"]>0:
        like_index = 1
        for like_type in like_summary["Counts"]:
            like_size= len(like_summary["Counts"])
            result_steps.config(text=f"Fetching likes...({like_index}/{like_size})")
            like_index +=1
            if like_summary["Counts"][like_type]>0:
                    data = get_post_associations(post_hash_hex,"REACTION", like_type)
                    if data and "Associations" in data:
                        for record in data["Associations"]:
                            if data[prof_resp][record[tpkbc]] is not None:
                                username = data[prof_resp][record[tpkbc]]["Username"]
                                public_key = data[prof_resp][record[tpkbc]][pkbc]
                                username_publickey[username] = public_key
                                print(f"  {like_type} by: {username}")
                                info["reaction_count"] = info.get("reaction_count",0) + 1
                                post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                                post_scores[post_hash_hex][username][f"{like_type}"] = post_scores[post_hash_hex][username].get(f"{like_type}", 0) + LIKE_SCORE

def update_polls(post,post_hash_hex,username_publickey,post_scores,info):
    if "PollOptions" in post["PostExtraData"]:
        result_steps.config(text="Fetching polls...")
        poll_summary = post_associations_counts(post_hash_hex,"POLL_RESPONSE",json.loads(post["PostExtraData"]["PollOptions"]))
        
        #print(poll_summary)
        if poll_summary:
            if "Total" in poll_summary:
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
                                        info["polls_count"] = info.get("polls_count",0) + 1
                                        post_scores[post_hash_hex][username] = post_scores[post_hash_hex].get(username, {})
                                        post_scores[post_hash_hex][username]["POLL"] = post_scores[post_hash_hex][username].get("POLL", 0) + POLL_SCORE

def update_following(user_scores1,username_publickey,user_public_key,username_follow):
    output_label.config(text=f"Fetching following...")
    follow_size= len(user_scores1)
    def process_username(username, username_publickey, user_public_key, FOLLOW_SCORE,local_counter):
        """Processes a single username and calculates the follow score."""
        global thread_counter  # Access the global counter
        public_key = username_publickey.get(username)
        isFollowing = is_following(public_key, user_public_key) if public_key else False
        follow_score = FOLLOW_SCORE if isFollowing else 0
        print(f"Thread {local_counter}: Processed {username}")  # Print the numbered message
        result_steps.config(text=f"Fetching follow...({username}/{follow_size})")
        return username, follow_score 

    def calculate_follow_scores(user_scores1, username_publickey, user_public_key, FOLLOW_SCORE, max_workers=5):
        """Calculates follow scores for multiple users using threads."""
        username_follow = {}
        local_counter = 0
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for username in user_scores1:
                local_counter += 1
                future = executor.submit(process_username, username, username_publickey, user_public_key, FOLLOW_SCORE, local_counter)
                futures.append(future)

        for future in futures:
            try:
                username, follow_score = future.result()
                username_follow[username] = follow_score
            except Exception as e:
                print(f"Error processing {username}: {e}")

        return username_follow

    username_follow = calculate_follow_scores(user_scores1, username_publickey, user_public_key, FOLLOW_SCORE, max_workers=5)  # Explicitly set max_workers=3
    return username_follow

def generate_csv(username,data):
    # Generate filename with current date and time
    now = datetime.datetime.now()
    filename = f"{username}_{len(data)}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
    # Write data to CSV file
    with open(filename, 'w', newline='' ,encoding="utf-8") as outfile:
        writer = csv.writer(outfile)

        # Write header row
        writer.writerow(["👤","💬","💎","🔁","📢","👍","❤️","👎","😥","😮","😠","😂","📊","➕","💯"])

        # Write data rows
        for username, details in data:
            row = [
                username,
                details["post_scores"].get('comment', ''),  # Use .get() with a default value
                details["post_scores"].get('diamond', ''),
                details["post_scores"].get('repost', ''),
                details["post_scores"].get('quote_repost', ''),
                details["post_scores"].get('LIKE', ''),
                details["post_scores"].get('LOVE', ''),
                details["post_scores"].get('DISLIKE', ''),
                details["post_scores"].get('SAD', ''),
                details["post_scores"].get('ASTONISHED', ''),
                details["post_scores"].get('ANGRY', ''),
                details["post_scores"].get('LAUGH', ''),
                details["post_scores"].get('POLL', ''),
                details.get('follow_score', ''),
                details.get('total_score', '')
            ]
            writer.writerow(row)
    print(f"{len(data)} users written to {filename}")

def generate_table(top_10):
    root = tk.Tk()
    root.title("Deso Stats Table")
    column_widths = {
        "Username": 120,  # Adjust as needed
        "comment": 40,
        "diamond": 40,
        "repost": 40,
        "quote_repost": 40,
        "LIKE": 40,
        "LOVE": 40,
        "DISLIKE": 40,
        "SAD": 40,
        "ASTONISHED": 40,
        "ANGRY": 40,
        "LAUGH": 40,
        "poll": 40,
        "Follow Score": 40,
        "Total Score": 40
    }

    tree = ttk.Treeview(root, columns=list(column_widths.keys()), show="headings")
    for col, width in column_widths.items():
        tree.heading(col, text=col)
        if col != "Username":
            tree.column(col, width=width, anchor=tk.CENTER)
        else:
            tree.column(col, width=width, anchor=tk.W)  #Left Align Username

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

    tree.place(x=100, y=100)
    tree.pack()
    root.mainloop()

lock = threading.Lock()

def process_post(post,post_scores,post_comments_body,user_public_key,username_publickey,info,NUM_POSTS_TO_FETCH):

    if stop_flag:
        output_label.config(text="Calculation stopped.")
        return
    post_hash_hex = post['PostHashHex']
    with lock:
        output_label.config(text="Calculating..."+str(info["post_index"])+"/"+str(NUM_POSTS_TO_FETCH))
        progress_bar["value"] = int((info["post_index"]*100)/NUM_POSTS_TO_FETCH)
        info["post_index"] = info.get("post_index",0) +1
        progress_bar.update_idletasks()
        entry_post_id.delete(0, tk.END) 
        entry_post_id.insert(tk.END, post_hash_hex)
    

    if post["Body"] == "":
        print("Skipping reposts")
        return
    post_scores[post_hash_hex] = {}
    post_comments_body[post_hash_hex] = {}
    
    post_comments_body[post_hash_hex]["comments"] = {}
    reader_public_key = user_public_key
    with lock:
        print("["+str(info["post_index"])+"]"+post_hash_hex)
    
    

    thread1 = threading.Thread(target=update_comments, args=(post_comments_body,post_hash_hex,reader_public_key,username_publickey,post_scores,info))
    thread2 = threading.Thread(target=update_diamonds, args=(post_hash_hex,user_public_key,username_publickey,post_scores,info))
    thread3 = threading.Thread(target=update_reposts, args=(post_hash_hex,user_public_key,post_scores,info))
    thread4 = threading.Thread(target=update_quote_reposts, args=(post_hash_hex,user_public_key,post_scores,info))
    thread5 = threading.Thread(target=update_reactions, args=(post_hash_hex,username_publickey,post_scores,info))
    thread6 = threading.Thread(target=update_polls, args=(post,post_hash_hex,username_publickey,post_scores,info))

    thread1.start()
    thread2.start()
    thread3.start()
    thread4.start()
    thread5.start()
    thread6.start()

    thread1.join()
    thread2.join()
    thread3.join()
    thread4.join()
    thread5.join()
    thread6.join()
    print("Thread end")
    return 1

def calculate_stats(username,user_pubkey,post_hash,output_label,NUM_POSTS_TO_FETCH):
    global stop_flag
    post_scores = {} 
    post_comments_body={}
    username_publickey = {}
    user_public_key = user_pubkey
    single_post_hash_check=post_hash
    output_label.config(text="Calculating...")  # Initial feedback

    if len(single_post_hash_check)>0:
        last_posts=[{"PostHashHex":single_post_hash_check,"Body":"Single","PostExtraData":{}}]
    else:
        last_posts = get_last_posts(user_public_key, NUM_POSTS_TO_FETCH)
    info={}
    info["post_index"]=0
    futures = []
    if last_posts:
        
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for post in last_posts:
                future = executor.submit(process_post, post,post_scores,post_comments_body,user_public_key,username_publickey,info,NUM_POSTS_TO_FETCH)
                futures.append(future)

        for future in futures:
            try:
                result=future.result()
               
                
            except Exception as e:
                print(f"Error processing {username}: {e}")


    user_scores1 = calculate_user_category_scores(post_scores)
    result_steps.config(text=f"calculate user category scores")
    username_follow={}

    label_all_users_count.config(text="All Users: "+str(len(user_scores1)))
    label_comment_count.config(text="Comments Count: "+str(info.get("comments_count",0)))
    label_diamond_count.config(text="Diamonds Lvl 1 Count: "+str(info.get("diamonds_lvl1_count",0)))
    label_diamond2_count.config(text="Diamonds Lvl 2 Count: "+str(info.get("diamonds_lvl2_count",0)))
    label_diamond3_count.config(text="Diamonds Lvl 3 Count: "+str(info.get("diamonds_lvl3_count",0)))
    label_diamond4_count.config(text="Diamonds Lvl 4 Count: "+str(info.get("diamonds_lvl4_count",0)))

    label_reposts_count.config(text="Reposts Count: "+str(info.get("reposts_count",0)))
    label_quote_reposts_count.config(text="Quote Reposts Count: "+str(info.get("quote_reposts_count",0)))
    label_reaction_count.config(text="Reaction Count: "+str(info.get("reaction_count",0)))
    label_polls_count.config(text="Polls Count: "+str(info.get("polls_count",0)))
    username_follow = update_following(user_scores1,username_publickey,user_public_key,username_follow)

    print("\nUser Post data:") 
    print(user_scores1)

    print("\nusername_follow:")
    print(username_follow)

    # Combine the data
    combined_data = combine_data(user_scores1, username_follow)

    sorted_data = sorted(combined_data.items(), key=lambda item: item[1]['total_score'], reverse=True)
    top_10 = sorted_data[:10]
    print()
    print("**Top 10 User Scores**")
    print_to_terminal("**Top 10 User Scores**")
    print_to_terminal("")
    i=1
    for record in top_10:
        total_score = record[1]['total_score']
        badge = ""
        if 300 <= total_score <= 500:
            badge = " 🥉"
        elif 501 <= total_score <= 1000:
            badge = " 🥈"
        elif total_score >= 1001:
            badge = " 🥇"
        print("["+str(i)+"] @"+record[0]+" :"+str(total_score)+badge)
        print_to_terminal("\n["+str(i)+"] @"+record[0]+" :"+str(total_score)+badge)
        i +=1
    print("**End of User Scores**")
    print()
    print_to_terminal("")
    print_to_terminal("**End of  User Scores**")

    print("**All User Scores**")
    i=1
    for record in sorted_data:
        print("["+str(i)+"] @"+record[0]+" :"+str(record[1]['total_score']))
        i +=1
    print("**End of All User Scores**")
    print()
    stop_flag = True
    result_steps.config(text="")
    generate_table(top_10)

    generate_csv(username,top_10)   #save top 10 to csv
    generate_csv(username,sorted_data) #save all users to csv

    output_label.config(text=f"Done")
    result_steps.config(text="")

def button_click():
    global calculation_thread,stop_flag
    try:
        
        if calculation_thread and calculation_thread.is_alive():
            output_label.config(text="Existing calculation is running.")
            return
        
        user = entry_username.get()
        post_hash = entry_post_id.get()

        if len(user)==0:
            output_label.config(text="Username Empty")
            return
        if len(entry_number_of_posts.get())==0:
            if len(post_hash)==0:
                output_label.config(text="Number of posts to check is Empty")
                return
        
        if len(user) != 55:
            user_data = get_single_profile(user)
            user_pub_key = user_data["Profile"]["PublicKeyBase58Check"]
        else:
            user_pub_key = user
        
        if len(post_hash)>0:
            NUM_POSTS_TO_FETCH=1
        else:
            NUM_POSTS_TO_FETCH = int(entry_number_of_posts.get())
        stop_flag = False  # Reset stop flag
        calculation_thread = threading.Thread(target=calculate_stats, args=(user,user_pub_key, post_hash, output_label,NUM_POSTS_TO_FETCH))
        calculation_thread.start()
     
    except Exception as e:
        output_label.config(text=f"Error: {e}")  # Display error if something goes wrong

def print_to_terminal(text):
        text_area.config(state='normal')  # Enable writing
        text_area.insert(tk.END, text + '\n')
        text_area.see(tk.END)  # Scroll to the end
        text_area.config(state='disabled') # Disable writing again

def stop_calculation():
    global stop_flag
    if stop_flag is False:
        stop_flag = True
        output_label.config(text="Stopping calculation...")


root = tk.Tk()
root.title("Deso Stats Calculator")
root.configure(bg=backround_colour)
root.geometry("750x900+100+100")
#Style setup
style = ttk.Style()
style.theme_use('clam')
style.configure("TButton", padding=5, relief="sunken", background="#03ac6f", foreground="black", border=0, font=("Arial", 12))  # Explicit font
style.map("TButton",
          background=[('pressed', "#009255"),('active', "#00a565")],
          foreground=[('pressed', 'black')],
          relief=[('pressed', 'sunken')]
          )
info_frame = tk.Frame(root, bg="#009255")  # width of new column
info_frame.grid(row=0, column=0, columnspan=2,rowspan=5, sticky="nsew",padx=5,pady=5)
label_info = ttk.Label(info_frame, text="Information", background="#009255", foreground=foreground, font=("Arial", 12))
label_all_users_count = ttk.Label(info_frame, text="All Users:", background="#009255", foreground=foreground, font=("Arial", 10))
label_comment_count = ttk.Label(info_frame, text="Comments Count: ", background="#009255", foreground=foreground, font=("Arial", 10))
label_diamond_count = ttk.Label(info_frame, text="Diamonds Lvl 1 Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_diamond2_count = ttk.Label(info_frame, text="Diamonds Lvl 2 Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_diamond3_count = ttk.Label(info_frame, text="Diamonds Lvl 3 Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_diamond4_count = ttk.Label(info_frame, text="Diamonds Lvl 4 Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_reposts_count = ttk.Label(info_frame, text="Reposts Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_quote_reposts_count = ttk.Label(info_frame, text="Quote Reposts Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_reaction_count = ttk.Label(info_frame, text="Reaction Count:", background="#009255", foreground=foreground, font=("Arial", 10))
label_polls_count = ttk.Label(info_frame, text="Polls Count:", background="#009255", foreground=foreground, font=("Arial", 10))

input_frame = tk.Frame(root, bg=backround_colour)  # width of new column
input_frame.grid(row=0, column=2, columnspan=3,rowspan=6, sticky="nsew",padx=5,pady=5)
input_frame.columnconfigure(0, weight=1)
label1 = ttk.Label(input_frame, text="User Public Key or Username:", background=backround_colour, foreground=foreground, font=("Arial", 12))
label1.grid(row=0, column=0, padx=2, pady=2,sticky="w")
entry_username = ttk.Entry(input_frame,font=("Arial", 12))
entry_username.grid(row=1, column=0, padx=2, pady=2, sticky="w")

label2 = ttk.Label(input_frame, text="Post ID:", background=backround_colour, foreground=foreground, font=("Arial", 12))
label2.grid(row=2, column=0, sticky="w", padx=2, pady=2)
entry_post_id = ttk.Entry(input_frame,font=("Arial", 12))
entry_post_id.grid(row=3, column=0, columnspan=3, padx=2, pady=2, sticky="we")

label3 = ttk.Label(input_frame, text="How many posts to check:", background=backround_colour, foreground=foreground, font=("Arial", 12))
label3.grid(row=4, column=0, sticky="w", padx=2, pady=2)
entry_number_of_posts = ttk.Entry(input_frame,font=("Arial", 12))
entry_number_of_posts.grid(row=5, column=0, padx=2, pady=2, sticky="w")

calculate_button = ttk.Button(root, text="Calculate", command=button_click)  # apply style here
calculate_button.grid(row=6, column=2, columnspan=1, pady=10)
stop_button = ttk.Button(root, text="Stop", command=stop_calculation)  # apply style here
stop_button.grid(row=6, column=3, columnspan=1, pady=10)
output_label = ttk.Label(root, text="", background=backround_colour, foreground=foreground, font=("Arial", 12))
output_label.grid(row=6, column=1, columnspan=4, sticky="w", pady=5)
# Progress bar setup
style.configure("TProgressbar", padding=5,  background="#03ac6f", foreground="black", border=0, font=("Arial", 12))  # Explicit font
progress_bar = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate") #increased length
progress_bar.grid(row=7, column=0, columnspan=4, sticky="ew", pady=5,padx=5) # Added sticky="ew"
progress_bar["maximum"] = 100  # Set a default maximum value
progress_bar.update_idletasks()  # Make sure it appears initially
label4 = ttk.Label(root, text="Instructions:\nTo check for last number of posts information \n1. Enter User Public Key or username\n2. Clear if there is any Post ID\n3. Enter How many posts to check\n\nTo check specific post information\n1. Enter User Public Key or username\n2. Enter Post ID", background=backround_colour, foreground="#D3D3D3", font=("Arial", 9))
label4.grid(row=8, column=0, columnspan=4, sticky="w", padx=5, pady=5)
result_steps = ttk.Label(root, text="", background=backround_colour, foreground=foreground, font=("Arial", 12))
result_steps.grid(row=8, column=2, columnspan=2, sticky="we", padx=5, pady=5)
text_area = tk.Text(root, height=20, width=80, bg="#009255", fg=foreground, font=("Arial", 12))
text_area.grid(row=9, column=0, columnspan=4, pady=10, padx=10)
text_area.config(state='disabled')
label_info.grid(row=0, column=0, sticky="we")
label_all_users_count.grid(row=1, column=0, sticky="we",padx=1, pady=1)
label_comment_count.grid(row=2, column=0, sticky="we",padx=1, pady=1)
label_diamond_count.grid(row=3, column=0, sticky="we",padx=1, pady=1)
label_diamond2_count.grid(row=4, column=0, sticky="we",padx=1, pady=1)
label_diamond3_count.grid(row=5, column=0, sticky="we",padx=1, pady=1)
label_diamond4_count.grid(row=6, column=0, sticky="we",padx=1, pady=1)
label_reposts_count.grid(row=7, column=0, sticky="we",padx=1, pady=1)
label_quote_reposts_count.grid(row=8, column=0, sticky="we",padx=1, pady=1)
label_reaction_count.grid(row=9, column=0, sticky="we",padx=1, pady=1)
label_polls_count.grid(row=10, column=0, sticky="we",padx=1, pady=1)
root.mainloop()
