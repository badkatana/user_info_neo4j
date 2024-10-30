import argparse
import logging
import requests
from neo4j import GraphDatabase
from tokens_data import token, uri, neo4j_user, neo4j_password


VK_ACCESS_TOKEN=token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
neo4j_uri =uri
neo4j_user =neo4j_user
neo4j_password = neo4j_password
driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

def vk_request(method, params):
    params['access_token'] = VK_ACCESS_TOKEN
    params['v'] = '5.199'
    response = requests.get(f'https://api.vk.com/method/{method}', params=params)
    if response.status_code != 200:
        logger.error(f"Ошибка запроса: {response.json()}")
        return None
    return response.json()

def create_user(tx, user_info):
    tx.run("MERGE (u:User {id: $id, name: $name, sex: $sex, home_town: $home_town})",
           id=user_info['id'], name=user_info['name'], sex=user_info['sex'], home_town=user_info['home_town'])

def create_group(tx, group_info):
    tx.run("MERGE (g:Group {id: $id, name: $name})",
           id=group_info['id'], name=group_info['name'])

def create_relationship(tx, user_id, group_id):
    tx.run("""
        MATCH (u:User {id: $user_id}), (g:Group {id: $group_id})
        MERGE (u)-[:SUBSCRIBES]->(g)
    """, user_id=user_id, group_id=group_id)

def create_follower_relationship(tx, user_id, follower_id):
    tx.run("""
        MATCH (u:User {id: $user_id}), (f:User {id: $follower_id})
        MERGE (u)-[:FOLLOWS]->(f)
    """, user_id=user_id, follower_id=follower_id)

def get_followers(user_id):
    followers = []
    followers_data = vk_request('users.getFollowers', {'user_id': user_id, 'fields': 'first_name,last_name,sex,city'})
    if followers_data and 'response' in followers_data:
        with driver.session() as session:
            for follower in followers_data['response']['items']:
                user_info = {
                    'id': follower['id'],
                    'name': f"{follower.get('first_name', '')} {follower.get('last_name', '')}",
                    'sex': follower.get('sex'),
                    'home_town': follower.get('city', {}).get('title', '')
                }
                session.write_transaction(create_user, user_info)
                logger.info(f"Добавлен пользователь: {user_info}")
                session.write_transaction(create_follower_relationship, user_id, follower['id'])
                followers.append(follower['id'])

    return followers


def get_subscriptions(user_id):
    subscriptions_data = vk_request('groups.get', {'user_id': user_id, 'extended': 1})
    print(subscriptions_data)
    if subscriptions_data and 'response' in subscriptions_data:
        with driver.session() as session:
            for group in subscriptions_data['response']['items']:
                group_info = {
                    'id': group['id'],
                    'name': group.get('name', '')
                }
                session.write_transaction(create_group, group_info)
                logger.info(f"Добавлена группа: {group_info}")
                session.write_transaction(create_relationship, user_id, group_info['id'])


def process_user_and_followers(user_id, depth=0):
    if depth < 3: 
        get_subscriptions(user_id)

        followers = get_followers(user_id)

        for follower_id in followers:
            process_user_and_followers(follower_id, depth + 1)


def query_database(query):
    with driver.session() as session:
        result = session.run(query)
        return [record for record in result]

def main():
    user_id = input("Введите ID пользователя для обработки: ")
    
    with driver.session() as session:
        user_info = {'id': user_id, 'name': '', 'sex': '', 'home_town': ''}
        session.write_transaction(create_user, user_info)
        logger.info(f"Добавлен пользователь: {user_info}")

        process_user_and_followers(user_id)

    total_users_query = "MATCH (u:User) RETURN count(u) AS total_users"
    total_groups_query = "MATCH (g:Group) RETURN count(g) AS total_groups"

    top_users_query = """
        MATCH (u:User)<-[:FOLLOWS]-(f)
        RETURN u.id AS user_id, count(f) AS follower_count
        ORDER BY follower_count DESC LIMIT 5
    """

    popular_groups_query = """
        MATCH (g:Group)<-[:SUBSCRIBES]-(u)
        RETURN g.id AS group_id, count(u) AS subscriber_count
        ORDER BY subscriber_count DESC LIMIT 5
    """

    mutual_followers_query = """
        MATCH (u1:User)-[:FOLLOWS]->(u2:User)
        WHERE u1 <> u2 AND (u2)-[:FOLLOWS]->(u1)
        RETURN u1.id AS user1, u2.id AS user2
    """

    print("Общая информация:")
    print("Всего пользователей:", query_database(total_users_query)[0]['total_users'])
    print("Всего групп:", query_database(total_groups_query)[0]['total_groups'])
    
    print("nТоп 5 пользователей по количеству подписчиков:")
    for record in query_database(top_users_query):
        print(f"Пользователь ID: {record['user_id']}, Количество подписчиков: {record['follower_count']}")

    print("nТоп 5 самых популярных групп:")
    for record in query_database(popular_groups_query):
        print(f"Группа ID: {record['group_id']}, Количество подписчиков: {record['subscriber_count']}")

    print("nПользователи, которые подписаны друг на друга:")
    for record in query_database(mutual_followers_query):
        print(f"Пользователь 1 ID: {record['user1']}, Пользователь 2 ID: {record['user2']}")

if __name__ == "__main__":
    main()
