"""Knowledge hub models."""

from sqlalchemy import DateTime, Integer, String, Text, func

from ..base import Column, Model


class KnowledgeCategory(Model):
    __tablename__ = "knowledge_categories"

    category_id = Column(Integer, primary_key=True)
    category_name = Column(String(128), unique=True, nullable=False)


class KnowledgePost(Model):
    __tablename__ = "knowledge_posts"

    post_id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category_id = Column(Integer)
    author = Column(String(128))
    image = Column(String(500))
    video = Column(String(500))
    status = Column(String(32), default="Published")
    views = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime)


class KnowledgeLike(Model):
    __tablename__ = "knowledge_likes"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, nullable=False)
    username = Column(String(128), nullable=False)


class KnowledgeComment(Model):
    __tablename__ = "knowledge_comments"

    comment_id = Column(Integer, primary_key=True)
    post_id = Column(Integer, nullable=False)
    username = Column(String(128), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp())


class KnowledgeReply(Model):
    __tablename__ = "knowledge_replies"

    reply_id = Column(Integer, primary_key=True)
    comment_id = Column(Integer, nullable=False)
    username = Column(String(128), nullable=False)
    reply = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp())
